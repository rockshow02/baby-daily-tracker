"""Privacy & Data Management Center — destructive actions are online-only."""
from pathlib import Path
import secrets

from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy import func

from extensions import db
from models import Child, ChildCaregiver, ChildInvite, User
from utils.access import get_accessible_child, get_accessible_children, resolve_role, ROLE_OWNER
from utils.auth import get_current_user_id
from utils.timezone_utils import now_wib


privacy_bp = Blueprint("privacy", __name__)
MAX_CONFIRMATION_BODY_BYTES = 8_192

# Count only, never return record contents. Technical rows (idempotency/audit)
# are deliberately shown separately from caregiver-entered records.
INVENTORY_TABLES = (
    ("feeding_logs", "Menyusui"),
    ("sleep_logs", "Tidur"),
    ("diaper_logs", "Popok"),
    ("pumping_logs", "Pompa ASI"),
    ("activity_logs", "Aktivitas"),
    ("growth_measurements", "Pertumbuhan"),
    ("doctor_visit_logs", "Kunjungan dokter"),
    ("temperature_logs", "Suhu"),
    ("illness_logs", "Riwayat sakit"),
    ("medication_logs", "Obat"),
    ("mood_logs", "Mood"),
    ("milestone_logs", "Momen penting"),
    ("child_vaccinations", "Vaksinasi"),
    ("child_medical_profiles", "Profil medis"),
    ("caregiver_audit_events", "Riwayat aktivitas caregiver"),
    ("reminders", "Pengingat"),
    ("medication_schedules", "Jadwal obat"),
    ("caregiver_handovers", "Serah-terima caregiver"),
)


def _current_user():
    user_id = get_current_user_id()
    return db.session.get(User, user_id) if user_id else None


def _parse_confirmation_payload():
    declared = request.content_length
    if declared is not None and declared > MAX_CONFIRMATION_BODY_BYTES:
        return None, (jsonify({"error": "Permintaan terlalu besar"}), 413)
    # Tetap bounded saat Content-Length hilang/bohong: baca maksimal N+1
    # byte dari stream, lalu seed cache Werkzeug untuk parsing JSON sekali.
    raw = request.stream.read(MAX_CONFIRMATION_BODY_BYTES + 1)
    if len(raw) > MAX_CONFIRMATION_BODY_BYTES:
        return None, (jsonify({"error": "Permintaan terlalu besar"}), 413)
    request._cached_data = raw
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "Data konfirmasi tidak valid"}), 400)
    return data, None


def _inventory(child):
    items = []
    total = 0
    for table_name, label in INVENTORY_TABLES:
        table = db.metadata.tables.get(table_name)
        count = 0
        if table is not None and "child_id" in table.c:
            count = db.session.query(func.count()).select_from(table).filter(table.c.child_id == child.id).scalar() or 0
        items.append({"key": table_name, "label": label, "count": count})
        total += count
    derived = (
        ("reminder_actions", "Aksi pengingat", "reminders", "reminder_id"),
        ("medication_dose_actions", "Riwayat dosis terjadwal", "medication_schedules", "schedule_id"),
        ("caregiver_handover_acknowledgements", "Konfirmasi serah-terima", "caregiver_handovers", "handover_id"),
    )
    for table_name, label, parent_name, foreign_key in derived:
        table = db.metadata.tables.get(table_name)
        parent = db.metadata.tables.get(parent_name)
        count = 0
        if table is not None and parent is not None:
            count = (
                db.session.query(func.count())
                .select_from(table.join(parent, table.c[foreign_key] == parent.c.id))
                .filter(parent.c.child_id == child.id)
                .scalar() or 0
            )
        items.append({"key": table_name, "label": label, "count": count})
        total += count
    caregiver_count = ChildCaregiver.query.filter_by(child_id=child.id).count() + 1
    return {
        "child": {"id": child.id, "name": child.name, "nickname": child.nickname, "role": None},
        "record_groups": items,
        "total_records": total,
        "caregiver_count": caregiver_count,
        "has_photo": bool(child.photo_filename),
    }


def _validated_photo_path(filename):
    if not filename or Path(filename).name != filename:
        return None
    root = (Path(current_app.root_path) / "uploads").resolve()
    unresolved = root / filename
    if unresolved.is_symlink():
        return None
    candidate = unresolved.resolve(strict=False)
    if candidate.parent != root:
        return None
    return candidate


@privacy_bp.route("/privacy/overview", methods=["GET"])
def privacy_overview():
    user = _current_user()
    if not user:
        return jsonify({"error": "Belum login"}), 401
    children = get_accessible_children(user.id)
    result = []
    for child in children:
        entry = _inventory(child)
        role = resolve_role(child, user.id)
        entry["child"]["role"] = role
        entry["capabilities"] = {
            "can_export": True,
            "can_delete_child": role == ROLE_OWNER,
            "can_leave_child": role != ROLE_OWNER,
        }
        result.append(entry)
    owned_count = sum(1 for c in children if c.user_id == user.id)
    return jsonify({
        "children": result,
        "account": {
            "owned_children": owned_count,
            "shared_children": len(children) - owned_count,
            "can_delete_account": owned_count == 0,
            "confirmation_text": "HAPUS AKUN",
            "deletion_mode": "erase_and_deactivate",
        },
    })


def _verify_confirmation(user, expected_text):
    data, error = _parse_confirmation_payload()
    if error:
        return None, error
    if not user.check_password(data.get("password", "")):
        return None, (jsonify({"error": "Password salah"}), 400)
    if data.get("confirmation", "").strip() != expected_text:
        return None, (jsonify({"error": "Teks konfirmasi tidak cocok"}), 400)
    return data, None


@privacy_bp.route("/privacy/children/<int:child_id>/leave", methods=["POST"])
def leave_child(child_id):
    user = _current_user()
    if not user:
        return jsonify({"error": "Belum login"}), 401
    child = get_accessible_child(child_id, user.id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404
    if child.user_id == user.id:
        return jsonify({"error": "Pemilik tidak bisa keluar. Hapus data anak atau pindahkan kepemilikan terlebih dahulu."}), 400
    _, error = _verify_confirmation(user, child.name)
    if error:
        return error
    membership = ChildCaregiver.query.filter_by(child_id=child.id, user_id=user.id).first()
    if not membership:
        return jsonify({"error": "Akses sudah tidak aktif"}), 409
    try:
        db.session.delete(membership)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Caregiver privacy leave transaction failed")
        return jsonify({"error": "Akses belum berubah. Silakan coba lagi."}), 500
    return jsonify({"success": True})


@privacy_bp.route("/privacy/children/<int:child_id>/delete", methods=["POST"])
def delete_child_data(child_id):
    user = _current_user()
    if not user:
        return jsonify({"error": "Belum login"}), 401
    child = get_accessible_child(child_id, user.id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404
    if child.user_id != user.id:
        return jsonify({"error": "Hanya pemilik anak yang bisa menghapus data ini"}), 403
    _, error = _verify_confirmation(user, child.name)
    if error:
        return error

    photo_path = _validated_photo_path(child.photo_filename)
    had_photo = bool(child.photo_filename)
    try:
        db.session.delete(child)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Child privacy deletion transaction failed")
        return jsonify({"error": "Data belum terhapus. Silakan coba lagi."}), 500

    cleanup_warning = False
    if had_photo:
        if photo_path is None:
            cleanup_warning = True
        else:
            try:
                photo_path.unlink(missing_ok=True)
            except OSError:
                cleanup_warning = True
                current_app.logger.warning("Child photo cleanup failed after database deletion")
    return jsonify({"success": True, "file_cleanup": "warning" if cleanup_warning else "ok"})


@privacy_bp.route("/privacy/account/delete", methods=["POST"])
def delete_account():
    user = _current_user()
    if not user:
        return jsonify({"error": "Belum login"}), 401
    if Child.query.filter_by(user_id=user.id).count():
        return jsonify({"error": "Selesaikan dulu semua anak yang masih Anda miliki sebelum menghapus akun."}), 409
    _, error = _verify_confirmation(user, "HAPUS AKUN")
    if error:
        return error

    # Cabut seluruh akses aktif dan token undangan yang dibuat akun ini.
    try:
        ChildCaregiver.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        ChildInvite.query.filter_by(created_by=user.id).delete(synchronize_session=False)
        ChildInvite.query.filter_by(used_by=user.id).update({"used_by": None}, synchronize_session=False)

        # Hapus identifier pribadi, tetapi pertahankan placeholder teknis agar
        # catatan historis lintas-caregiver tidak dialihkan ke identitas lain.
        user.name = "Akun dihapus"
        user.email = f"deleted-{user.id}-{secrets.token_hex(12)}@invalid.local"
        user.telegram_chat_id = None
        user.set_password(secrets.token_urlsafe(48))
        user.is_active = False
        user.deleted_at = now_wib()
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Account privacy deletion transaction failed")
        return jsonify({"error": "Akun belum terhapus. Silakan coba lagi."}), 500
    session.pop("user_id", None)
    return jsonify({"success": True, "mode": "erase_and_deactivate"})
