import os
import uuid
import secrets
from datetime import datetime, date, timedelta

from flask import Blueprint, request, jsonify, session, current_app, send_from_directory
from werkzeug.utils import secure_filename

from extensions import db
from models import Child, VaccineSchedule, ChildVaccination, ChildCaregiver, ChildInvite, User
from utils.timezone_utils import today_wib
from utils.access import get_accessible_child, get_accessible_children, get_caregiver_role
from utils.auth import get_current_user_id

children_bp = Blueprint("children", __name__)

ALLOWED_PHOTO_EXT = {"png", "jpg", "jpeg", "webp"}
MAX_PHOTO_SIZE_MB = 5


def _require_login():
    return get_current_user_id()


def _owned_child(child_id, user_id):
    return get_accessible_child(child_id, user_id)


def _age_in_months(birth_date):
    today = today_wib()
    return (today.year - birth_date.year) * 12 + (today.month - birth_date.month) - (
        1 if today.day < birth_date.day else 0
    )


def _add_months(d, months):
    """Tambah N bulan ke tanggal, aman buat tanggal akhir bulan (mis. 31 Jan + 1 bulan -> 28/29 Feb)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    import calendar
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


MAX_CHILD_AGE_YEARS = 6  # aplikasi ini dirancang untuk 0-5 tahun (sesuai data WHO/IDAI yang dipakai)


def _validate_birth_date(birth_date):
    """
    Return pesan error kalau tanggal lahir tidak masuk akal untuk aplikasi ini,
    atau None kalau valid. Mencegah kasus salah ketik seperti '02031999' yang
    ke-parse jadi tanggal valid tapi jelas bukan usia bayi/balita.
    """
    today = today_wib()
    if birth_date > today:
        return "Tanggal lahir tidak boleh di masa depan"

    age_days = (today - birth_date).days
    max_days = MAX_CHILD_AGE_YEARS * 365
    if age_days > max_days:
        return (
            f"Tanggal lahir menunjukkan usia lebih dari {MAX_CHILD_AGE_YEARS} tahun. "
            "Aplikasi ini dirancang untuk anak usia 0-5 tahun. Mohon cek kembali tanggalnya."
        )
    return None


def _uploads_dir():
    path = os.path.join(current_app.root_path, "uploads")
    os.makedirs(path, exist_ok=True)
    return path


# ---------- CHILDREN ----------

@children_bp.route("/children", methods=["GET"])
def list_children():
    user_id = _require_login()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401
    children = get_accessible_children(user_id)
    return jsonify([c.to_dict() for c in children])


@children_bp.route("/children", methods=["POST"])
def create_child():
    user_id = _require_login()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    data = request.get_json() or {}
    name = data.get("name", "").strip()
    birth_date_str = data.get("birth_date")
    if not name or not birth_date_str:
        return jsonify({"error": "Nama dan tanggal lahir wajib diisi"}), 400

    try:
        birth_date = datetime.strptime(birth_date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Format tanggal harus YYYY-MM-DD"}), 400

    date_error = _validate_birth_date(birth_date)
    if date_error:
        return jsonify({"error": date_error}), 400

    birth_weight_kg = data.get("birth_weight_kg")
    birth_height_cm = data.get("birth_height_cm")
    if birth_weight_kg is not None and not (0.5 <= float(birth_weight_kg) <= 8):
        return jsonify({"error": "Berat lahir tidak wajar (0.5-8 kg)"}), 400
    if birth_height_cm is not None and not (20 <= float(birth_height_cm) <= 70):
        return jsonify({"error": "Tinggi lahir tidak wajar (20-70 cm)"}), 400

    child = Child(
        user_id=user_id,
        name=name,
        nickname=(data.get("nickname") or "").strip() or None,
        birth_date=birth_date,
        gender=data.get("gender"),
        birth_weight_kg=birth_weight_kg,
        birth_height_cm=birth_height_cm,
    )
    db.session.add(child)
    db.session.flush()  # biar dapet child.id sebelum commit
    db.session.add(ChildCaregiver(child_id=child.id, user_id=user_id, role="owner"))
    db.session.commit()
    return jsonify(child.to_dict()), 201


@children_bp.route("/children/<int:child_id>", methods=["GET"])
def get_child(child_id):
    user_id = _require_login()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    child = _owned_child(child_id, user_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404
    return jsonify(child.to_dict())


@children_bp.route("/children/<int:child_id>", methods=["PUT", "DELETE"])
def update_or_delete_child(child_id):
    user_id = _require_login()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    child = _owned_child(child_id, user_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    if request.method == "DELETE":
        if get_caregiver_role(child_id, user_id) != "owner":
            return jsonify({"error": "Hanya pemilik anak yang bisa menghapus data anak"}), 403
        # hapus juga file foto kalau ada
        if child.photo_filename:
            path = os.path.join(_uploads_dir(), child.photo_filename)
            if os.path.exists(path):
                os.remove(path)
        db.session.delete(child)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
    if "name" in data:
        child.name = data["name"]
    if "nickname" in data:
        child.nickname = (data["nickname"] or "").strip() or None
    if "birth_date" in data:
        new_birth_date = datetime.strptime(data["birth_date"], "%Y-%m-%d").date()
        date_error = _validate_birth_date(new_birth_date)
        if date_error:
            return jsonify({"error": date_error}), 400
        child.birth_date = new_birth_date
    if "gender" in data:
        child.gender = data["gender"]
    if "birth_weight_kg" in data:
        child.birth_weight_kg = data["birth_weight_kg"]
    if "birth_height_cm" in data:
        child.birth_height_cm = data["birth_height_cm"]
    db.session.commit()
    return jsonify(child.to_dict())


# ---------- FOTO ----------

@children_bp.route("/children/<int:child_id>/photo", methods=["POST"])
def upload_child_photo(child_id):
    user_id = _require_login()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    child = _owned_child(child_id, user_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    if "photo" not in request.files:
        return jsonify({"error": "File foto tidak ditemukan"}), 400

    file = request.files["photo"]
    if file.filename == "":
        return jsonify({"error": "File foto kosong"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_PHOTO_EXT:
        return jsonify({"error": "Format harus PNG, JPG, atau WEBP"}), 400

    file.seek(0, os.SEEK_END)
    size_mb = file.tell() / (1024 * 1024)
    file.seek(0)
    if size_mb > MAX_PHOTO_SIZE_MB:
        return jsonify({"error": f"Ukuran foto maksimal {MAX_PHOTO_SIZE_MB}MB"}), 400

    # hapus foto lama kalau ada
    if child.photo_filename:
        old_path = os.path.join(_uploads_dir(), child.photo_filename)
        if os.path.exists(old_path):
            os.remove(old_path)

    filename = secure_filename(f"child{child_id}_{uuid.uuid4().hex[:8]}.{ext}")
    file.save(os.path.join(_uploads_dir(), filename))

    child.photo_filename = filename
    db.session.commit()
    return jsonify(child.to_dict())


@children_bp.route("/uploads/<path:filename>", methods=["GET"])
def get_upload(filename):
    return send_from_directory(_uploads_dir(), filename)


# ---------- VAKSINASI ----------

@children_bp.route("/vaccine-schedule", methods=["GET"])
def list_vaccine_schedule():
    """Tabel acuan jadwal imunisasi Kemenkes — tidak butuh login, data statis."""
    items = VaccineSchedule.query.order_by(VaccineSchedule.order_index.asc()).all()
    return jsonify([v.to_dict() for v in items])


def _build_vaccination_list(child, age_months):
    schedule = VaccineSchedule.query.order_by(VaccineSchedule.order_index.asc()).all()
    existing = {cv.vaccine_schedule_id: cv for cv in child.vaccinations}

    result = []
    for v in schedule:
        cv = existing.get(v.id)
        given_early = False
        if cv and cv.given and cv.given_date:
            age_at_given = (
                (cv.given_date.year - child.birth_date.year) * 12
                + (cv.given_date.month - child.birth_date.month)
                - (1 if cv.given_date.day < child.birth_date.day else 0)
            )
            given_early = age_at_given < v.recommended_age_months
        result.append({
            "vaccine_schedule_id": v.id,
            "vaccine_name": v.vaccine_name,
            "dose_label": v.dose_label,
            "recommended_age_months": v.recommended_age_months,
            "is_optional": v.is_optional,
            "category": v.category,
            "notes": v.notes,
            "due": v.recommended_age_months <= age_months,
            "given": cv.given if cv else False,
            "given_date": cv.given_date.isoformat() if (cv and cv.given_date) else None,
            "given_early": given_early,
            "given_notes": cv.notes if cv else None,
        })
    return result


@children_bp.route("/children/<int:child_id>/next-vaccine", methods=["GET"])
def next_vaccine(child_id):
    """
    Vaksin WAJIB berikutnya yang perlu diperhatikan: kalau ada yang sudah
    jatuh tempo tapi belum dicatat, itu yang diprioritaskan (ditandai overdue).
    Kalau nggak ada yang overdue, tampilkan vaksin wajib berikutnya yang
    belum dicatat, urut dari usia rekomendasi paling dekat.
    """
    user_id = _require_login()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    child = _owned_child(child_id, user_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    age_months = _age_in_months(child.birth_date)
    all_vax = _build_vaccination_list(child, age_months)
    wajib = [v for v in all_vax if v["category"] == "wajib" and not v["given"]]

    if not wajib:
        return jsonify({"has_next": False, "message": "Semua vaksin wajib sudah tercatat lengkap."})

    overdue = [v for v in wajib if v["due"]]
    upcoming = [v for v in wajib if not v["due"]]

    if overdue:
        target = min(overdue, key=lambda v: v["recommended_age_months"])
        status = "overdue"
    else:
        target = min(upcoming, key=lambda v: v["recommended_age_months"])
        status = "upcoming"

    months_until = target["recommended_age_months"] - age_months
    estimated_date = _add_months(child.birth_date, target["recommended_age_months"])

    return jsonify({
        "has_next": True,
        "status": status,  # 'overdue' | 'upcoming'
        "vaccine_name": target["vaccine_name"],
        "recommended_age_months": target["recommended_age_months"],
        "months_until": months_until,
        "estimated_date": estimated_date.isoformat(),
        "overdue_count": len(overdue),
    })


@children_bp.route("/children/<int:child_id>/vaccinations", methods=["GET"])
def list_child_vaccinations(child_id):
    user_id = _require_login()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    child = _owned_child(child_id, user_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    age_months = _age_in_months(child.birth_date)
    return jsonify({"age_months": age_months, "vaccinations": _build_vaccination_list(child, age_months)})


@children_bp.route("/children/<int:child_id>/vaccinations", methods=["POST"])
def update_child_vaccinations(child_id):
    """
    Bulk update status vaksinasi.
    Body: {"items": [{"vaccine_schedule_id": 1, "given": true, "given_date": "2026-01-01", "notes": "..."}]}

    Vaksin yang diberikan sebelum usia rekomendasi TIDAK diblokir (dokter kadang
    memang mempercepat jadwal karena alasan medis, kejar jadwal, dll) — tapi tetap
    ditandai sebagai "given_early" di response, biar keliatan jelas di riwayat/laporan
    dan orang tua bisa nyimpen alasannya di field notes.
    """
    user_id = _require_login()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    child = _owned_child(child_id, user_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    data = request.get_json() or {}
    items = data.get("items", [])

    for item in items:
        vaccine_schedule_id = item.get("vaccine_schedule_id")
        if not vaccine_schedule_id:
            continue

        cv = ChildVaccination.query.filter_by(
            child_id=child_id, vaccine_schedule_id=vaccine_schedule_id
        ).first()
        if not cv:
            cv = ChildVaccination(child_id=child_id, vaccine_schedule_id=vaccine_schedule_id)
            db.session.add(cv)

        cv.given = bool(item.get("given", False))
        given_date_str = item.get("given_date")
        cv.given_date = datetime.strptime(given_date_str, "%Y-%m-%d").date() if given_date_str else None
        if "notes" in item:
            cv.notes = item["notes"]

    db.session.commit()

    age_months = _age_in_months(child.birth_date)
    return jsonify({"age_months": age_months, "vaccinations": _build_vaccination_list(child, age_months)})


# ---------- MULTI-CAREGIVER ----------

@children_bp.route("/children/<int:child_id>/caregivers", methods=["GET"])
def list_caregivers(child_id):
    user_id = _require_login()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    child = get_accessible_child(child_id, user_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    caregivers = ChildCaregiver.query.filter_by(child_id=child_id).order_by(ChildCaregiver.created_at.asc()).all()
    return jsonify([c.to_dict() for c in caregivers])


@children_bp.route("/children/<int:child_id>/caregivers/<int:caregiver_user_id>", methods=["DELETE"])
def remove_caregiver(child_id, caregiver_user_id):
    """Cabut akses caregiver dari anak. Cuma owner yang boleh, dan owner nggak bisa mencabut dirinya sendiri."""
    user_id = _require_login()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    if get_caregiver_role(child_id, user_id) != "owner":
        return jsonify({"error": "Hanya pemilik anak yang bisa mengelola caregiver"}), 403

    if caregiver_user_id == user_id:
        return jsonify({"error": "Pemilik tidak bisa mencabut akses diri sendiri"}), 400

    cc = ChildCaregiver.query.filter_by(child_id=child_id, user_id=caregiver_user_id).first()
    if not cc:
        return jsonify({"error": "Caregiver tidak ditemukan"}), 404

    db.session.delete(cc)
    db.session.commit()
    return jsonify({"success": True})


@children_bp.route("/children/<int:child_id>/invite", methods=["POST"])
def create_invite(child_id):
    """Bikin kode undangan buat nambah caregiver baru. Berlaku 7 hari, sekali pakai.
    Semua pengasuh (bukan cuma pemilik) boleh bikin, biar nggak harus lewat satu orang doang."""
    user_id = _require_login()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    child = get_accessible_child(child_id, user_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    code = secrets.token_hex(4).upper()  # cth. "A1B2C3D4"
    invite = ChildInvite(
        child_id=child_id,
        code=code,
        created_by=user_id,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.session.add(invite)
    db.session.commit()
    return jsonify(invite.to_dict()), 201


@children_bp.route("/children/join", methods=["POST"])
def join_child():
    """Pakai kode undangan buat dapet akses ke anak orang lain (mis. pasangan)."""
    user_id = _require_login()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    data = request.get_json() or {}
    code = (data.get("code") or "").strip().upper()
    if not code:
        return jsonify({"error": "Kode undangan wajib diisi"}), 400

    invite = ChildInvite.query.filter_by(code=code).first()
    if not invite:
        return jsonify({"error": "Kode undangan tidak ditemukan"}), 404
    if invite.used_by:
        return jsonify({"error": "Kode undangan sudah pernah dipakai"}), 400
    if invite.expires_at < datetime.utcnow():
        return jsonify({"error": "Kode undangan sudah kedaluwarsa"}), 400

    existing = ChildCaregiver.query.filter_by(child_id=invite.child_id, user_id=user_id).first()
    if existing:
        return jsonify({"error": "Kamu sudah punya akses ke anak ini"}), 400

    db.session.add(ChildCaregiver(child_id=invite.child_id, user_id=user_id, role="caregiver"))
    invite.used_by = user_id
    invite.used_at = datetime.utcnow()
    db.session.commit()

    child = Child.query.get(invite.child_id)
    return jsonify({"success": True, "child": child.to_dict()}), 201