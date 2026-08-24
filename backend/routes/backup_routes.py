import base64
import binascii
import os
import re
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, session, request, current_app
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import (
    Child, ChildMedicalProfile, FeedingLog, SleepLog, DiaperLog, PumpingLog, ActivityLog,
    MedicationLog, TemperatureLog, DoctorVisitLog, IllnessLog,
    GrowthMeasurement, ChildVaccination, VaccineSchedule, MoodLog, MilestoneLog,
)
from routes.children_routes import ALLOWED_PHOTO_EXT, MAX_PHOTO_SIZE_MB
from utils.access import get_accessible_child, resolve_role, ROLE_OWNER, WRITE_ROLES
from utils.auth import get_current_user_id
from utils.medical_profile_engine import MedicalProfileValidationError, validate_medical_profile_payload
from utils.timezone_utils import to_wib_naive

backup_bp = Blueprint("backup", __name__)

EXPORT_VERSION = 1

# Base64 mengembang ~4/3 dari ukuran biner aslinya -- batas ini dipakai buat
# nolak string base64 yang KEGEDEAN SEBELUM di-decode penuh ke memory,
# konsisten sama MAX_PHOTO_SIZE_MB yang sama dipakai endpoint upload foto
# biasa (children_routes.py) biar nggak ada dua kebijakan ukuran foto yang
# beda-beda di app ini.
MAX_PHOTO_ENCODED_CHARS = ((MAX_PHOTO_SIZE_MB * 1024 * 1024) * 4 // 3) + 1024


def _owned_child(child_id):
    user_id = get_current_user_id()
    if not user_id:
        return None
    return get_accessible_child(child_id, user_id)


def _iso(d):
    return d.isoformat() if d else None


def _uploads_dir():
    return os.path.join(current_app.root_path, "uploads")


def _safe_remove(path):
    """
    Hapus SATU file di path yang PERSIS diketahui (TIDAK PERNAH glob/hapus
    direktori). Kegagalan hapus (mis. file udah kehapus proses lain, race
    langka, dst) SENGAJA ditelan di sini -- requirement #10: kegagalan
    cleanup TIDAK PERNAH boleh nutupin/gantiin exception asli yang lagi
    ditangani si pemanggil (rollback DB / format backup tidak valid).
    """
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _validate_photo_ext(raw_ext):
    """
    Balikin ekstensi tervalidasi (lowercase, TANPA titik) kalau `raw_ext`
    aman dipakai bikin path, None kalau nggak. HARUS dipanggil SEBELUM
    ekstensi mentah dari file backup dipakai buat apa pun -- ekstensi dari
    JSON backup TIDAK PERNAH dipercaya langsung (bisa berisi path traversal
    `../..`, path absolut `/tmp/x` / `C:\\x`, separator direktori, ekstensi
    ganda `jpg.exe`, dll). Regex `[a-z0-9]+` menolak SEMUA karakter di luar
    huruf/angka (titik, slash, backslash, spasi, dst) sekaligus, lalu
    kecocokannya dicek lagi terhadap allowlist yang SAMA dipakai endpoint
    upload foto biasa (children_routes.ALLOWED_PHOTO_EXT).
    """
    if not raw_ext or not isinstance(raw_ext, str):
        return None
    ext = raw_ext.strip().lower()
    if not re.fullmatch(r"[a-z0-9]+", ext):
        return None
    if ext not in ALLOWED_PHOTO_EXT:
        return None
    return ext


def _decode_photo_base64(raw_b64):
    """
    Decode base64 SECARA KETAT. Balikin bytes kalau valid, None kalau nggak
    (foto dilewati dengan aman -- gagal decode foto TIDAK PERNAH gagalin
    seluruh import, lihat backend/docs/ROLES_PERMISSIONS.md).

    Kebijakan yang didokumentasikan di ROLES_PERMISSIONS.md:
    - `validate=True` bikin base64.b64decode() nolak SEMUA karakter di luar
      alfabet base64 standar -- termasuk whitespace/newline apa pun (spasi,
      tab, baris baru) DAN padding yang salah -- sebagai binascii.Error.
      export_json() (lewat base64.b64encode().decode("ascii")) TIDAK PERNAH
      nyisipin whitespace, jadi payload valid dari export_json() nggak akan
      pernah kena tolak karena ini.
    - Prefix data-URL (`data:image/png;base64,...`) TIDAK didukung. Prefix
      ini otomatis ketolak juga oleh validate=True (':' ';' ',' bukan
      karakter alfabet base64) -- jadi literal prefix-nya TIDAK PERNAH
      ketulis ke file, cukup ditolak lewat jalur error yang sama.
    - Ukuran string ENCODED dibatasi SEBELUM decode penuh (rasio ekspansi
      base64 ~4/3), biar payload raksasa nggak didecode penuh ke memory
      dulu baru ketauan kegedean.
    """
    if not raw_b64 or not isinstance(raw_b64, str):
        return None
    if len(raw_b64) > MAX_PHOTO_ENCODED_CHARS:
        return None
    try:
        decoded = base64.b64decode(raw_b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not decoded:
        return None
    if len(decoded) > MAX_PHOTO_SIZE_MB * 1024 * 1024:
        return None
    return decoded


def _write_photo_file(child_id, ext, photo_bytes):
    """
    Tulis file foto ke path yang SEPENUHNYA server-generated (ekstensi udah
    tervalidasi lewat _validate_photo_ext, nama file TIDAK PERNAH dari input
    pengguna). Pakai mode 'xb' (exclusive creation) biar file yang sudah ada
    TIDAK PERNAH ketimpa -- kalau nama hasil random-nya somehow bentrok,
    dicoba ulang dengan nama baru, bukan nimpa yang lama.

    Balikin (filename, full_path) kalau sukses, (None, None) kalau gagal --
    kalau nulisnya gagal di tengah jalan, file parsial yang sempat kebuat
    langsung dihapus (dan kegagalan hapus itu sendiri nggak pernah dibiarin
    nutupin kegagalan tulis yang asli).
    """
    uploads_dir = _uploads_dir()
    os.makedirs(uploads_dir, exist_ok=True)
    for _ in range(5):
        filename = f"child{child_id}_{uuid.uuid4().hex[:8]}.{ext}"
        candidate_path = os.path.join(uploads_dir, filename)
        try:
            with open(candidate_path, "xb") as f:
                f.write(photo_bytes)
            return filename, candidate_path
        except FileExistsError:
            continue
        except OSError:
            _safe_remove(candidate_path)
            return None, None
    return None, None


def _restore_photo_from_base64(child_id, raw_photo_base64, raw_photo_ext):
    """
    Pulihkan foto anak dari data base64 di file backup JSON. Balikin
    (filename, path) HANYA kalau file BENERAN sukses ditulis penuh;
    (None, None) kalau dilewati dengan aman (ekstensi/base64/ukuran nggak
    valid) -- ini nggak pernah gagalin seluruh import (requirement #14),
    dan nggak pernah nyisain file di disk kalau balikinnya (None, None).
    """
    ext = _validate_photo_ext(raw_photo_ext)
    if not ext:
        return None, None
    photo_bytes = _decode_photo_base64(raw_photo_base64)
    if not photo_bytes:
        return None, None
    return _write_photo_file(child_id, ext, photo_bytes)


@backup_bp.route("/children/<int:child_id>/export-json", methods=["GET"])
def export_json(child_id):
    """
    Backup lengkap semua data anak dalam format JSON, buat dipulihkan
    di device lain lewat endpoint /children/import-json.
    """
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    # Child Medical Profile & Emergency Card Phase 1 -- kebijakan peran
    # profil medis LEBIH KETAT dari backup anak secara umum (yang sudah
    # bisa diakses editor/viewer lewat _owned_child di atas) -- CUMA
    # Owner/Editor yang boleh membawa data profil medis+kontak darurat
    # ikut ke dalam backup, konsisten sama GET /medical-profile
    # (Viewer selalu 403 di sana). Viewer TETAP bisa backup data anak
    # LAINNYA seperti biasa, cuma field `medical_profile` yang
    # dikecualikan (bukan seluruh endpoint ini ditolak).
    include_medical_profile = resolve_role(child, get_current_user_id()) in WRITE_ROLES
    medical_profile_row = (
        ChildMedicalProfile.query.filter_by(child_id=child_id).first() if include_medical_profile else None
    )

    photo_base64 = None
    photo_ext = None
    if child.photo_filename:
        path = os.path.join(_uploads_dir(), child.photo_filename)
        if os.path.exists(path):
            with open(path, "rb") as f:
                photo_base64 = base64.b64encode(f.read()).decode("ascii")
            photo_ext = child.photo_filename.rsplit(".", 1)[-1]

    illnesses = IllnessLog.query.filter_by(child_id=child_id).order_by(IllnessLog.id.asc()).all()
    illness_local_id = {ill.id: idx for idx, ill in enumerate(illnesses)}

    vaccinations = ChildVaccination.query.filter_by(child_id=child_id).all()

    data = {
        "export_version": EXPORT_VERSION,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "child": {
            "name": child.name,
            "birth_date": _iso(child.birth_date),
            "gender": child.gender,
            "birth_weight_kg": child.birth_weight_kg,
            "birth_height_cm": child.birth_height_cm,
            "photo_base64": photo_base64,
            "photo_ext": photo_ext,
        },
        "feeding_logs": [
            {
                "timestamp": l.timestamp.isoformat(),
                "feed_type": l.feed_type,
                "duration_minutes": l.duration_minutes,
                "volume_ml": l.volume_ml,
                "breast_side": l.breast_side,
                "notes": l.notes,
            }
            for l in FeedingLog.query.filter_by(child_id=child_id).all()
        ],
        "sleep_logs": [
            {
                "start_time": l.start_time.isoformat(),
                "end_time": l.end_time.isoformat() if l.end_time else None,
                "sleep_type": l.sleep_type,
                "notes": l.notes,
            }
            for l in SleepLog.query.filter_by(child_id=child_id).all()
        ],
        "diaper_logs": [
            {
                "timestamp": l.timestamp.isoformat(),
                "diaper_type": l.diaper_type,
                "consistency": l.consistency,
                "color": l.color,
                "notes": l.notes,
            }
            for l in DiaperLog.query.filter_by(child_id=child_id).all()
        ],
        "pumping_logs": [
            {
                "timestamp": l.timestamp.isoformat(),
                "duration_minutes": l.duration_minutes,
                "volume_ml": l.volume_ml,
                "breast_side": l.breast_side,
                "notes": l.notes,
            }
            for l in PumpingLog.query.filter_by(child_id=child_id).all()
        ],
        "activity_logs": [
            {
                "timestamp": l.timestamp.isoformat(),
                "activity_type": l.activity_type,
                "duration_minutes": l.duration_minutes,
                "notes": l.notes,
            }
            for l in ActivityLog.query.filter_by(child_id=child_id).all()
        ],
        "medication_logs": [
            {
                "timestamp": l.timestamp.isoformat(),
                "medication_name": l.medication_name,
                "dosage": l.dosage,
                "notes": l.notes,
                "illness_local_id": illness_local_id.get(l.illness_id),
            }
            for l in MedicationLog.query.filter_by(child_id=child_id).all()
        ],
        "temperature_logs": [
            {
                "timestamp": l.timestamp.isoformat(),
                "temperature_celsius": l.temperature_celsius,
                "method": l.method,
                "notes": l.notes,
            }
            for l in TemperatureLog.query.filter_by(child_id=child_id).all()
        ],
        "doctor_visits": [
            {
                "visit_date": _iso(v.visit_date),
                "doctor_name": v.doctor_name,
                "clinic_name": v.clinic_name,
                "reason": v.reason,
                "diagnosis": v.diagnosis,
                "next_visit_date": _iso(v.next_visit_date),
                "notes": v.notes,
            }
            for v in DoctorVisitLog.query.filter_by(child_id=child_id).all()
        ],
        "illness_logs": [
            {
                "illness_name": ill.illness_name,
                "start_date": _iso(ill.start_date),
                "end_date": _iso(ill.end_date),
                "symptoms": ill.symptoms,
                "notes": ill.notes,
            }
            for ill in illnesses
        ],
        "growth_measurements": [
            {
                "measured_date": _iso(g.measured_date),
                "weight_kg": g.weight_kg,
                "height_cm": g.height_cm,
                "head_circumference_cm": g.head_circumference_cm,
                "notes": g.notes,
            }
            for g in GrowthMeasurement.query.filter_by(child_id=child_id).all()
        ],
        "vaccinations": [
            {
                "vaccine_name": cv.vaccine.vaccine_name,
                "given": cv.given,
                "given_date": _iso(cv.given_date),
            }
            for cv in vaccinations
        ],
        "mood_logs": [
            {"timestamp": l.timestamp.isoformat(), "mood": l.mood, "notes": l.notes}
            for l in MoodLog.query.filter_by(child_id=child_id).all()
        ],
        "milestone_logs": [
            {
                "milestone_type": l.milestone_type,
                "custom_label": l.custom_label,
                "achieved_date": _iso(l.achieved_date),
                "notes": l.notes,
            }
            for l in MilestoneLog.query.filter_by(child_id=child_id).all()
        ],
        # `None` kalau anak ini belum pernah punya profil medis SAMA
        # SEKALI, ATAUPUN kalau pengekspornya Viewer (lihat
        # `include_medical_profile` di atas) -- backward compatible
        # dengan backup versi lama yang nggak punya key ini sama sekali
        # (import_json:` data.get("medical_profile")` di bawah).
        "medical_profile": (
            {
                "blood_type": medical_profile_row.blood_type,
                "allergies": list(medical_profile_row.allergies or []),
                "conditions": list(medical_profile_row.conditions or []),
                "primary_doctor_name": medical_profile_row.primary_doctor_name,
                "primary_clinic_name": medical_profile_row.primary_clinic_name,
                "primary_clinic_phone": medical_profile_row.primary_clinic_phone,
                "emergency_contact_name": medical_profile_row.emergency_contact_name,
                "emergency_contact_relationship": medical_profile_row.emergency_contact_relationship,
                "emergency_contact_phone": medical_profile_row.emergency_contact_phone,
                "emergency_instructions": medical_profile_row.emergency_instructions,
            }
            if medical_profile_row else None
        ),
    }

    return jsonify(data)


@backup_bp.route("/children/import-json", methods=["POST"])
def import_json():
    """
    Pulihkan backup JSON dari export-json jadi anak baru di akun yang
    sedang login. Selalu bikin anak BARU (tidak menimpa anak yang sudah ada),
    biar aman kalau backup-nya diimport lebih dari sekali.
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    data = request.get_json()
    if not data or "child" not in data:
        return jsonify({"error": "Format file backup tidak valid"}), 400

    c = data["child"]
    if not isinstance(c, dict) or not c.get("name") or not c.get("birth_date"):
        return jsonify({"error": "Data anak di file backup tidak lengkap"}), 400

    # `photo_path` dilacak DI LUAR blok try — kalau transaksi gagal
    # SETELAH file foto ini kebuat, blok except di bawah bakal ngehapus
    # file-nya lagi (Issue 1, requirement #9: nggak boleh nyisain file
    # foto yatim kalau child/log-nya sendiri di-rollback).
    photo_path = None

    try:
        birth_date = datetime.strptime(c["birth_date"], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return jsonify({"error": "Format tanggal lahir di file backup tidak valid"}), 400

    # Kepemilikan anak yang diimport SEPENUHNYA dari `user_id` (akun yang
    # LAGI LOGIN dan ngelakuin import ini) — TIDAK PERNAH dari field
    # apa pun di dalam file JSON (`user_id`/`owner_id`/`created_by_user_id`/
    # `role` kalau ada di file backup-nya SAMA SEKALI nggak pernah dibaca
    # di endpoint ini). Lihat models.py:ChildCaregiver docstring +
    # backend/docs/ROLES_PERMISSIONS.md — pemilik SENGAJA TIDAK PERNAH
    # punya baris `child_caregivers` (role di situ CUMA boleh
    # 'editor'/'viewer', ditegakkan CHECK constraint), jadi endpoint ini
    # TIDAK PERNAH bikin baris ChildCaregiver buat pengimpor.
    child = Child(
        user_id=user_id,
        name=c["name"],
        birth_date=birth_date,
        gender=c.get("gender"),
        birth_weight_kg=c.get("birth_weight_kg"),
        birth_height_cm=c.get("birth_height_cm"),
    )
    db.session.add(child)

    try:
        db.session.flush()  # biar dapet child.id sebelum commit

        if c.get("photo_base64"):
            # `_restore_photo_from_base64` cuma balikin path kalau file
            # BENERAN sukses ditulis penuh (requirement #8) -- kalau
            # dilewati (None, None), `photo_path` TETAP None di sini dan
            # `child.photo_filename` TETAP nggak keisi, jadi nggak ada file
            # yatim yang bisa nyangkut kayak bug lama (lihat requirement
            # #6-7: candidate path baru dilacak SETELAH validasi lengkap
            # dan tulisnya beneran sukses, bukan sebelum).
            filename, saved_path = _restore_photo_from_base64(
                child.id, c["photo_base64"], c.get("photo_ext", "jpg"),
            )
            if filename:
                photo_path = saved_path
                child.photo_filename = filename

        # `created_by_user_id` diisi PENGIMPOR (user_id) buat SEMUA record
        # yang diimport — bukan diambil dari file JSON (yang nggak pernah
        # punya kolom ini sama sekali di export_json() di atas, dan kalau
        # pun ada nggak pernah dipercaya — lihat requirement #11) dan
        # bukan NULL — pengimpor-lah yang SECARA NYATA "membuat" baris
        # ini di akun ini sekarang, konsisten sama cara create_feeding_log
        # dkk ngisi created_by_user_id dari user yang lagi request, bukan
        # dari input klien.
        for l in data.get("feeding_logs", []):
            db.session.add(FeedingLog(
                child_id=child.id, created_by_user_id=user_id,
                timestamp=to_wib_naive(l["timestamp"]),
                feed_type=l["feed_type"], duration_minutes=l.get("duration_minutes"),
                volume_ml=l.get("volume_ml"), breast_side=l.get("breast_side"), notes=l.get("notes"),
            ))

        for l in data.get("sleep_logs", []):
            db.session.add(SleepLog(
                child_id=child.id, created_by_user_id=user_id,
                start_time=to_wib_naive(l["start_time"]),
                end_time=to_wib_naive(l["end_time"]) if l.get("end_time") else None,
                sleep_type=l.get("sleep_type", "siang"), notes=l.get("notes"),
            ))

        for l in data.get("diaper_logs", []):
            db.session.add(DiaperLog(
                child_id=child.id, created_by_user_id=user_id, timestamp=to_wib_naive(l["timestamp"]),
                diaper_type=l["diaper_type"], consistency=l.get("consistency"),
                color=l.get("color"), notes=l.get("notes"),
            ))

        for l in data.get("pumping_logs", []):
            db.session.add(PumpingLog(
                child_id=child.id, created_by_user_id=user_id, timestamp=to_wib_naive(l["timestamp"]),
                duration_minutes=l.get("duration_minutes"), volume_ml=l.get("volume_ml"),
                breast_side=l.get("breast_side"), notes=l.get("notes"),
            ))

        for l in data.get("activity_logs", []):
            db.session.add(ActivityLog(
                child_id=child.id, created_by_user_id=user_id, timestamp=to_wib_naive(l["timestamp"]),
                activity_type=l["activity_type"], duration_minutes=l.get("duration_minutes"),
                notes=l.get("notes"),
            ))

        for l in data.get("temperature_logs", []):
            db.session.add(TemperatureLog(
                child_id=child.id, created_by_user_id=user_id, timestamp=to_wib_naive(l["timestamp"]),
                temperature_celsius=l["temperature_celsius"], method=l.get("method", "ketiak"),
                notes=l.get("notes"),
            ))

        for v in data.get("doctor_visits", []):
            db.session.add(DoctorVisitLog(
                child_id=child.id, created_by_user_id=user_id,
                visit_date=datetime.strptime(v["visit_date"], "%Y-%m-%d").date(),
                doctor_name=v.get("doctor_name"), clinic_name=v.get("clinic_name"),
                reason=v.get("reason"), diagnosis=v.get("diagnosis"),
                next_visit_date=datetime.strptime(v["next_visit_date"], "%Y-%m-%d").date() if v.get("next_visit_date") else None,
                notes=v.get("notes"),
            ))

        illness_objs = {}
        for idx, ill in enumerate(data.get("illness_logs", [])):
            obj = IllnessLog(
                child_id=child.id, created_by_user_id=user_id, illness_name=ill["illness_name"],
                start_date=datetime.strptime(ill["start_date"], "%Y-%m-%d").date(),
                end_date=datetime.strptime(ill["end_date"], "%Y-%m-%d").date() if ill.get("end_date") else None,
                symptoms=ill.get("symptoms"), notes=ill.get("notes"),
            )
            db.session.add(obj)
            illness_objs[idx] = obj
        db.session.flush()  # biar obj.id keisi

        for l in data.get("medication_logs", []):
            illness_id = None
            local_id = l.get("illness_local_id")
            if local_id is not None and local_id in illness_objs:
                illness_id = illness_objs[local_id].id
            db.session.add(MedicationLog(
                child_id=child.id, created_by_user_id=user_id, illness_id=illness_id,
                timestamp=to_wib_naive(l["timestamp"]),
                medication_name=l["medication_name"], dosage=l.get("dosage"), notes=l.get("notes"),
            ))

        for g in data.get("growth_measurements", []):
            db.session.add(GrowthMeasurement(
                child_id=child.id, created_by_user_id=user_id,
                measured_date=datetime.strptime(g["measured_date"], "%Y-%m-%d").date(),
                weight_kg=g.get("weight_kg"), height_cm=g.get("height_cm"),
                head_circumference_cm=g.get("head_circumference_cm"), notes=g.get("notes"),
            ))

        vaccine_by_name = {v.vaccine_name: v for v in VaccineSchedule.query.all()}
        for v in data.get("vaccinations", []):
            schedule = vaccine_by_name.get(v["vaccine_name"])
            if not schedule:
                continue
            db.session.add(ChildVaccination(
                child_id=child.id, vaccine_schedule_id=schedule.id,
                given=v.get("given", False),
                given_date=datetime.strptime(v["given_date"], "%Y-%m-%d").date() if v.get("given_date") else None,
            ))

        for l in data.get("mood_logs", []):
            db.session.add(MoodLog(
                child_id=child.id, created_by_user_id=user_id, timestamp=to_wib_naive(l["timestamp"]),
                mood=l["mood"], notes=l.get("notes"),
            ))

        for l in data.get("milestone_logs", []):
            db.session.add(MilestoneLog(
                child_id=child.id, created_by_user_id=user_id, milestone_type=l["milestone_type"],
                custom_label=l.get("custom_label"),
                achieved_date=datetime.strptime(l["achieved_date"], "%Y-%m-%d").date(),
                notes=l.get("notes"),
            ))

        # Child Medical Profile & Emergency Card Phase 1 -- `None`/key
        # nggak ada SAMA SEKALI (backup lama dari sebelum fitur ini ada)
        # -> dilewati dengan aman, TIDAK bikin baris ChildMedicalProfile
        # apa pun (backward compatible, requirement eksplisit). Kalau
        # ADA, divalidasi lewat FUNGSI VALIDASI YANG SAMA PERSIS dipakai
        # PUT /medical-profile (utils/medical_profile_engine.py) --
        # bukan aturan validasi kedua yang bisa hanyut beda -- jadi
        # backup dengan data yang nggak valid (versi lama yang formatnya
        # beda, atau diedit manual) HARUS gagal total (masuk except di
        # bawah), BUKAN diam-diam terpotong/diterima sebagian.
        # `last_reviewed_at`/`last_reviewed_by` SENGAJA TIDAK diimport
        # apa pun keadaannya -- profil yang baru dipulihkan di device/akun
        # LAIN dianggap "belum pernah diperiksa ulang di sini", metadata
        # siapa yang mereview di akun ASAL nggak relevan/valid dipindah
        # ke akun pengimpor.
        raw_medical_profile = data.get("medical_profile")
        if raw_medical_profile is not None:
            fields = validate_medical_profile_payload(raw_medical_profile)
            db.session.add(ChildMedicalProfile(child_id=child.id, **fields))

        db.session.commit()
    except (KeyError, ValueError, TypeError, AttributeError):
        # Data di dalam file backup-nya sendiri nggak lengkap/nggak valid
        # (field wajib kosong, tanggal/waktu salah format, dst) — ini
        # INPUT TIDAK VALID yang DIHARAPKAN bisa kejadian (file backup
        # rusak/lama/diedit manual), jadi balikin 400 yang jelas, BUKAN
        # 500 generik. `db.session.rollback()` + hapus file foto (kalau
        # sempat kebuat) biar TIDAK ADA anak/catatan/foto yatim yang
        # nyangkut — import gagal = gagal total, nggak ada yang keimport
        # sebagian.
        db.session.rollback()
        _safe_remove(photo_path)
        return jsonify({"error": "Format data di file backup tidak valid"}), 400
    except IntegrityError:
        # Pelanggaran constraint database (mis. CHECK/FK) dari data yang
        # diimport — SAMA-SAMA "input tidak valid yang diharapkan bisa
        # kejadian" (file backup dari versi lama/rusak), bukan kegagalan
        # server — 400, bukan 500 generik. Rollback + bersihin foto SAMA
        # persis kayak cabang di atas.
        db.session.rollback()
        _safe_remove(photo_path)
        return jsonify({"error": "Data di file backup tidak konsisten dan tidak bisa disimpan"}), 400
    except Exception:
        # Kegagalan BENERAN nggak terduga (disk penuh, DB down, dst) —
        # tetap rollback + bersihin foto dulu, TAPI biarkan handler
        # error global yang nyeterilin responsnya (pola yang sama dipakai
        # semua route lain di app ini, lihat utils/observability.py).
        db.session.rollback()
        _safe_remove(photo_path)
        raise

    return jsonify({"success": True, "child": {**child.to_dict(), "role": ROLE_OWNER}}), 201