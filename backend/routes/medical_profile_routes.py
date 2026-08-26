"""
Child Medical Profile & Emergency Card — Phase 1. Lihat
backend/docs/MEDICAL_PROFILE.md buat kontrak lengkapnya.

ONLINE-ONLY SENGAJA (lihat dokumen, bagian "Kebijakan offline") --
TIDAK ADA endpoint di sini yang boleh diantrikan offline
(frontend/src/api/client.js:OFFLINE_QUEUEABLE_PATHS TIDAK PERNAH
menyertakan path di bawah ini) -- profil medis + kontak darurat
lengkap TERLALU sensitif buat disimpan di antrian offline yang didesain
buat mutasi terbatas biasa (1-2 field per record), bukan brankas data
privat penuh.

TIDAK ADA proses background -- PDF Kartu Darurat SELALU dirender
SINKRON, di memori, per-request (lihat utils/emergency_card_pdf.py),
PERSIS prinsip PythonAnywhere Free yang sudah ditegakkan di seluruh app.
"""
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file

from extensions import db
from models import ChildMedicalProfile
from utils.access import get_accessible_child, resolve_role, WRITE_ROLES
from utils.audit import (
    EMERGENCY_CARD_PDF_EXPORT_ENTITY_TYPE, MEDICAL_PROFILE_REVIEWED_ENTITY_TYPE,
    diff_snapshots, record_audit_event, snapshot_fields,
)
from utils.auth import get_current_user_id
from utils.emergency_card_pdf import render_emergency_card_pdf, safe_filename_component
from utils.emergency_card_report import build_emergency_card_summary
from utils.emergency_card_snapshot import (
    SnapshotTokenInvalidError, SnapshotTokenUnauthorizedError,
    decode_snapshot_token, digest_emergency_card_report, digests_match, generate_snapshot_token,
)
from utils.medical_profile_engine import MedicalProfileValidationError, validate_medical_profile_payload
from utils.timezone_utils import now_wib

medical_profile_bp = Blueprint("medical_profile", __name__)

NO_ACCESS_MESSAGE = "Anda tidak punya izin untuk mengakses profil medis anak ini."
NO_PROFILE_YET_MESSAGE = "Belum ada profil medis untuk anak ini — isi dan simpan dulu sebelum menandai sudah diperiksa ulang."
MISSING_SNAPSHOT_TOKEN_MESSAGE = "Token pratinjau tidak ditemukan. Muat ulang pratinjau Kartu Darurat sebelum mengunduh PDF."
INVALID_SNAPSHOT_TOKEN_MESSAGE = "Token pratinjau tidak valid atau sudah kedaluwarsa. Muat ulang pratinjau Kartu Darurat."
UNAUTHORIZED_SNAPSHOT_TOKEN_MESSAGE = "Token pratinjau ini tidak berlaku untuk permintaan ini. Muat ulang pratinjau Kartu Darurat."
STALE_SNAPSHOT_MESSAGE = "Data Kartu Darurat berubah sejak pratinjau dibuat. Muat ulang pratinjau sebelum mengunduh PDF."

# Batas ukuran body KHUSUS endpoint ini -- jauh lebih ketat dari
# MAX_CONTENT_LENGTH global aplikasi (6MB, buat upload foto). Body PUT
# profil medis SEHARUSNYA cuma berisi <=30 entri alergi + <=30 entri
# kondisi (masing-masing field pendek, lihat utils/medical_profile_engine.py)
# + beberapa field kontak/teks pendek -- 20KB SUDAH sangat longgar.
MAX_MEDICAL_PROFILE_BODY_BYTES = 20_000

# Body endpoint PDF Kartu Darurat CUMA berisi 1 field (`snapshot_token`,
# string token bertanda tangan itsdangerous -- lihat
# utils/emergency_card_snapshot.py) -- token yang PALING PANJANG pun
# (claims + tanda tangan HMAC + encoding base64url) jauh di bawah 2KB;
# 4KB SUDAH margin sangat longgar, TETAP jauh lebih ketat dari batas
# PUT profil (20KB) apalagi batas global aplikasi (6MB) -- requirement:
# "apply a tight endpoint-specific raw-byte limit".
MAX_EMERGENCY_CARD_PDF_BODY_BYTES = 4_096
_OVERSIZED_RESPONSE = ({"error": "Ukuran permintaan terlalu besar"}, 413)


def _require_login_and_child(child_id):
    """(child, error_response_atau_None) -- pola SAMA PERSIS routes/reminder_routes.py."""
    user_id = get_current_user_id()
    if not user_id:
        return None, (jsonify({"error": "Belum login"}), 401)
    child = get_accessible_child(child_id, user_id)
    if not child:
        return None, (jsonify({"error": "Anak tidak ditemukan"}), 404)
    return child, None


def _capabilities(role):
    """
    Kebijakan Phase 1: Owner & Editor SAMA (penuh), Viewer TIDAK
    PUNYA akses sama sekali ke profil medis/Emergency Card (beda dari
    section sensitif lain di app ini yang tetap boleh Viewer BACA,
    lihat backend/docs/MEDICAL_PROFILE.md bagian Roles).
    """
    write = role in WRITE_ROLES
    return {
        "can_view_medical_profile": write,
        "can_edit_medical_profile": write,
        "can_preview_emergency_card": write,
        "can_export_emergency_card": write,
    }


def _require_medical_profile_access(child_id):
    """
    (child, user_id, role, capabilities, error_response_atau_None).

    Viewer (ATAUPUN role apa pun di luar Owner/Editor) SELALU dapet
    `403` yang SAMA PERSIS di sini -- terlepas anak ini SUDAH punya
    profil medis atau belum (requirement: "do not reveal whether a
    profile exists"). Dicek SEDINI mungkin, SEBELUM body/profil
    disentuh sama sekali -- termasuk SEBELUM ukuran body dicek
    (requirement: "Viewer oversized requests must still receive a
    uniform 403, not a size-dependent response that leaks capability").
    """
    child, err = _require_login_and_child(child_id)
    if err:
        return None, None, None, None, err
    user_id = get_current_user_id()
    role = resolve_role(child, user_id)
    capabilities = _capabilities(role)
    if not capabilities["can_view_medical_profile"]:
        return None, None, None, None, (jsonify({"error": NO_ACCESS_MESSAGE}), 403)
    return child, user_id, role, capabilities, None


def _read_json_body_within_limit(max_bytes=MAX_MEDICAL_PROFILE_BODY_BYTES):
    """
    Bounded-read SAMA PERSIS routes/doctor_consultation_routes.py:_read_json_body_within_limit
    -- lihat docstring di sana buat penjelasan lengkap kenapa cuma
    ngecek Content-Length aja NGGAK CUKUP. `max_bytes` dibikin parameter
    (bukan konstanta tetap) biar 1 fungsi ini dipakai ULANG buat KEDUA
    endpoint yang butuh body JSON di blueprint ini -- PUT profil
    (`MAX_MEDICAL_PROFILE_BODY_BYTES`, default) DAN PDF Kartu Darurat
    (`MAX_EMERGENCY_CARD_PDF_BODY_BYTES`, jauh lebih kecil karena body-nya
    cuma 1 token) -- TANPA menduplikasi logic bounded-read 2x.
    """
    if request.content_length is not None and request.content_length > max_bytes:
        return None, _OVERSIZED_RESPONSE
    raw = request.stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        return None, _OVERSIZED_RESPONSE
    request._cached_data = raw
    return request.get_json(silent=True), None


def _empty_profile_dict(child_id):
    """Bentuk 'belum ada profil' -- field yang SAMA PERSIS shape-nya dengan ChildMedicalProfile.to_dict(), biar frontend nggak perlu nge-cek 2 bentuk respons yang beda."""
    return {
        "id": None, "child_id": child_id, "blood_type": None, "allergies": [], "conditions": [],
        "primary_doctor_name": None, "primary_clinic_name": None, "primary_clinic_phone": None,
        "emergency_contact_name": None, "emergency_contact_relationship": None, "emergency_contact_phone": None,
        "emergency_instructions": None, "last_reviewed_at": None, "last_reviewed_by_name": None,
        "created_at": None, "updated_at": None,
    }


@medical_profile_bp.route("/children/<int:child_id>/medical-profile", methods=["GET"])
def get_medical_profile(child_id):
    child, user_id, role, capabilities, err = _require_medical_profile_access(child_id)
    if err:
        return err
    profile = ChildMedicalProfile.query.filter_by(child_id=child_id).first()
    body = profile.to_dict() if profile else _empty_profile_dict(child_id)
    return jsonify({"profile": body, "capabilities": capabilities})


@medical_profile_bp.route("/children/<int:child_id>/medical-profile", methods=["PUT"])
def update_medical_profile(child_id):
    child, user_id, role, capabilities, err = _require_medical_profile_access(child_id)
    if err:
        return err

    data, size_err = _read_json_body_within_limit()
    if size_err:
        payload, status = size_err
        return jsonify(payload), status
    if not isinstance(data, dict):
        return jsonify({"error": "Format data tidak valid"}), 400

    try:
        fields = validate_medical_profile_payload(data)
    except MedicalProfileValidationError as exc:
        return jsonify({"error": exc.message}), 400

    now = now_wib()
    profile = ChildMedicalProfile.query.filter_by(child_id=child_id).first()
    is_new = profile is None

    if is_new:
        profile = ChildMedicalProfile(child_id=child_id)
        db.session.add(profile)
        before = None
    else:
        before = snapshot_fields(profile, "medical_profile")

    for field, value in fields.items():
        setattr(profile, field, value)
    db.session.flush()  # biar profile.id keisi (baris baru) sebelum dipakai audit

    if is_new:
        record_audit_event(
            child_id=child_id, actor_user_id=user_id, action="create",
            entity_type="medical_profile", entity_id=profile.id, recorded_at=now,
        )
    else:
        # PUT snapshot penuh yang ISINYA SAMA PERSIS (no-op) TIDAK PERNAH
        # menghasilkan baris audit -- diff_snapshots() balikin [] kalau
        # bener-bener nggak ada field yang berubah nilainya sama sekali.
        changed = diff_snapshots(before, snapshot_fields(profile, "medical_profile"), "medical_profile")
        if changed:
            record_audit_event(
                child_id=child_id, actor_user_id=user_id, action="update",
                entity_type="medical_profile", entity_id=profile.id, changed_fields=changed, recorded_at=now,
            )
    db.session.commit()
    return jsonify({"profile": profile.to_dict(), "capabilities": capabilities})


@medical_profile_bp.route("/children/<int:child_id>/medical-profile/review", methods=["POST"])
def review_medical_profile(child_id):
    """
    "Tandai sudah diperiksa ulang" -- aksi TERPISAH dari PUT (caregiver
    bisa mengonfirmasi profilnya masih akurat SEKARANG tanpa mengubah
    satu field pun), diaudit lewat entity_type tersendiri
    (MEDICAL_PROFILE_REVIEWED_ENTITY_TYPE), BUKAN sebagai "update" field
    biasa.
    """
    child, user_id, role, capabilities, err = _require_medical_profile_access(child_id)
    if err:
        return err
    if not capabilities["can_edit_medical_profile"]:
        return jsonify({"error": NO_ACCESS_MESSAGE}), 403

    profile = ChildMedicalProfile.query.filter_by(child_id=child_id).first()
    if not profile:
        return jsonify({"error": NO_PROFILE_YET_MESSAGE}), 400

    now = now_wib()
    profile.last_reviewed_at = now
    profile.last_reviewed_by_user_id = user_id
    db.session.flush()
    record_audit_event(
        child_id=child_id, actor_user_id=user_id, action="create",
        entity_type=MEDICAL_PROFILE_REVIEWED_ENTITY_TYPE, entity_id=profile.id, recorded_at=now,
    )
    db.session.commit()
    return jsonify({"profile": profile.to_dict(), "capabilities": capabilities})


@medical_profile_bp.route("/children/<int:child_id>/emergency-card/preview", methods=["POST"])
def preview_emergency_card(child_id):
    """
    Lihat backend/docs/MEDICAL_PROFILE.md bagian "Konsistensi snapshot
    preview -> PDF (token bertanda tangan)" + docstring
    utils/emergency_card_snapshot.py. `now` di-sample SEKALI di sini --
    dipakai buat isi laporan (usia, "generated_at", obat rutin aktif
    SAAT INI) DAN ikut ditandatangani di dalam `snapshot_token` (field
    `preview_at`), biar endpoint PDF bisa membangun ulang laporan yang
    SAMA PERSIS tanpa perlu menyimpan apa pun di server.
    """
    child, user_id, role, capabilities, err = _require_medical_profile_access(child_id)
    if err:
        return err
    if not capabilities["can_preview_emergency_card"]:
        return jsonify({"error": NO_ACCESS_MESSAGE}), 403

    profile = ChildMedicalProfile.query.filter_by(child_id=child_id).first()
    now = now_wib()
    summary = build_emergency_card_summary(child, profile, now)
    digest = digest_emergency_card_report(summary)
    snapshot_token = generate_snapshot_token(
        child_id=child_id, user_id=user_id, preview_at=now.isoformat(), report_digest=digest,
    )
    summary["capabilities"] = capabilities
    summary["snapshot_token"] = snapshot_token
    return jsonify(summary)


@medical_profile_bp.route("/children/<int:child_id>/emergency-card/pdf", methods=["POST"])
def export_emergency_card_pdf(child_id):
    """
    Urutan pengecekan SENGAJA (lihat backend/docs/MEDICAL_PROFILE.md):
    (1) login+akses anak, (2) otorisasi export Owner/Editor, (3) bounded
    body read, (4) body harus objek JSON, (5) tanda tangan+kedaluwarsa
    token, (6) token harus milik anak+user yang SAMA, (7) bangun ulang
    laporan pakai `preview_at` dari token (BUKAN now_wib() baru), (8)
    hash pakai helper kanonik yang SAMA PERSIS dipakai preview, (9)
    bandingkan digest TIMING-SAFE, (10) render PDF CUMA kalau cocok.
    TIDAK PERNAH merender PDF ATAUPUN menulis baris audit buat request
    yang ditolak di langkah mana pun.
    """
    child, user_id, role, capabilities, err = _require_medical_profile_access(child_id)
    if err:
        return err
    # Otorisasi DULUAN, SEBELUM body (apalagi tokennya) disentuh sama
    # sekali -- konsisten sama routes/doctor_consultation_routes.py:export_consultation_pdf
    # DAN requirement eksplisit: "Viewer always receives the same 403,
    # regardless of token/body validity or size".
    if not capabilities["can_export_emergency_card"]:
        return jsonify({"error": NO_ACCESS_MESSAGE}), 403

    data, size_err = _read_json_body_within_limit(MAX_EMERGENCY_CARD_PDF_BODY_BYTES)
    if size_err:
        payload, status = size_err
        return jsonify(payload), status
    if not isinstance(data, dict):
        return jsonify({"error": "Format data tidak valid"}), 400

    snapshot_token = data.get("snapshot_token")
    if not snapshot_token or not isinstance(snapshot_token, str):
        return jsonify({"error": MISSING_SNAPSHOT_TOKEN_MESSAGE}), 400

    try:
        claims = decode_snapshot_token(snapshot_token, child_id=child_id, user_id=user_id)
    except SnapshotTokenUnauthorizedError:
        return jsonify({"error": UNAUTHORIZED_SNAPSHOT_TOKEN_MESSAGE}), 403
    except SnapshotTokenInvalidError:
        return jsonify({"error": INVALID_SNAPSHOT_TOKEN_MESSAGE}), 400

    try:
        preview_at = datetime.fromisoformat(claims["preview_at"])
    except (KeyError, TypeError, ValueError):
        # Praktis MUSTAHIL kejadian (claims sudah lolos verifikasi tanda
        # tangan itsdangerous, jadi isinya persis apa yang server SENDIRI
        # tandatangani) -- tetap ditangani secara defensif, BUKAN
        # dianggap "aman diteruskan begitu saja".
        return jsonify({"error": INVALID_SNAPSHOT_TOKEN_MESSAGE}), 400

    profile = ChildMedicalProfile.query.filter_by(child_id=child_id).first()
    summary = build_emergency_card_summary(child, profile, preview_at)
    current_digest = digest_emergency_card_report(summary)
    if not digests_match(current_digest, claims.get("digest")):
        return jsonify({"error": STALE_SNAPSHOT_MESSAGE}), 409

    buffer = render_emergency_card_pdf(summary)

    # `export_now` (waktu EKSPOR sebenarnya, BUKAN `preview_at` yang
    # dibekukan) dipakai CUMA buat metadata audit + nama file -- dua hal
    # ini TIDAK memengaruhi kesetaraan isi laporan (bukan bagian dari
    # digest, lihat utils/emergency_card_snapshot.py), jadi tetap aman
    # mencerminkan waktu unduh yang SEBENARNYA walau lebih belakangan
    # dari waktu preview.
    export_now = now_wib()

    # Audit CUMA buat PDF export (bukan preview) -- pola SAMA PERSIS
    # Doctor Consultation. `entity_id=0` -- TIDAK ADA baris database
    # yang jadi acuan PDF ini (kartu ini SENGAJA nggak pernah disimpan
    # permanen). Isi kartu (golongan darah/alergi/kontak/dst) TIDAK
    # PERNAH masuk baris audit ini.
    record_audit_event(
        child_id=child_id, actor_user_id=user_id, action="create",
        entity_type=EMERGENCY_CARD_PDF_EXPORT_ENTITY_TYPE, entity_id=0, recorded_at=export_now,
    )
    db.session.commit()

    filename = f"kartu-darurat-{safe_filename_component(child.nickname or child.name)}-{export_now.date().isoformat()}.pdf"
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)
