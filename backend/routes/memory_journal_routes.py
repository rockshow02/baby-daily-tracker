from datetime import date

from flask import Blueprint, jsonify, request, send_file

from extensions import db
from models import MemoryJournalEntry
from utils.access import WRITE_ROLES, can_delete_record, get_accessible_child, resolve_role
from utils.audit import diff_snapshots, record_audit_event, snapshot_fields
from utils.auth import get_current_user_id
from utils.memory_journal_images import JournalImageError, process_journal_image, validated_journal_path
from utils.timezone_utils import now_wib, today_wib

memory_journal_bp = Blueprint("memory_journal", __name__)


def _context(child_id):
    user_id = get_current_user_id()
    child = get_accessible_child(child_id, user_id) if user_id else None
    return user_id, child


def _serialize(entry, role, user_id):
    data = entry.to_dict()
    data.update(photo_url=f"/memory-journal/{entry.id}/photo",
                can_edit=can_delete_record(role, entry.created_by_user_id, user_id),
                can_delete=can_delete_record(role, entry.created_by_user_id, user_id))
    return data


def _parse_date(value):
    try:
        parsed = date.fromisoformat(value or "")
    except (TypeError, ValueError):
        return None
    return parsed if parsed <= today_wib() else None


@memory_journal_bp.route("/children/<int:child_id>/memory-journal", methods=["GET", "POST"])
def collection(child_id):
    user_id, child = _context(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404
    role = resolve_role(child, user_id)
    if request.method == "GET":
        entries = (MemoryJournalEntry.query.filter_by(child_id=child_id)
                   .order_by(MemoryJournalEntry.occurred_date.desc(), MemoryJournalEntry.id.desc())
                   .limit(100).all())
        return jsonify({"items": [_serialize(e, role, user_id) for e in entries],
                        "can_create": role in WRITE_ROLES,
                        "can_manage_storage": role == "owner"})
    if role not in WRITE_ROLES:
        return jsonify({"error": "Peran Anda hanya bisa melihat galeri"}), 403
    occurred_date = _parse_date(request.form.get("occurred_date"))
    caption = (request.form.get("caption") or "").strip() or None
    if not occurred_date:
        return jsonify({"error": "Tanggal momen tidak valid atau berada di masa depan"}), 400
    if caption and len(caption) > 500:
        return jsonify({"error": "Caption maksimal 500 karakter"}), 400
    try:
        filename, size, width, height = process_journal_image(request.files.get("photo"), child_id)
    except JournalImageError as exc:
        return jsonify({"error": str(exc)}), 400
    path = validated_journal_path(filename)
    try:
        entry = MemoryJournalEntry(child_id=child_id, created_by_user_id=user_id,
            occurred_date=occurred_date, caption=caption, photo_filename=filename,
            photo_size_bytes=size, photo_width=width, photo_height=height)
        db.session.add(entry); db.session.flush()
        record_audit_event(child_id=child_id, actor_user_id=user_id, action="create",
            entity_type="memory_journal", entity_id=entry.id, recorded_at=occurred_date)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if path: path.unlink(missing_ok=True)
        raise
    return jsonify(_serialize(entry, role, user_id)), 201


@memory_journal_bp.route("/memory-journal/<int:entry_id>", methods=["PUT", "DELETE"])
def item(entry_id):
    entry = db.session.get(MemoryJournalEntry, entry_id)
    if not entry:
        return jsonify({"error": "Momen tidak ditemukan"}), 404
    user_id, child = _context(entry.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403
    role = resolve_role(child, user_id)
    if not can_delete_record(role, entry.created_by_user_id, user_id):
        return jsonify({"error": "Anda tidak punya izin untuk mengubah momen ini"}), 403
    if request.method == "DELETE":
        path = validated_journal_path(entry.photo_filename)
        record_audit_event(child_id=entry.child_id, actor_user_id=user_id, action="delete",
            entity_type="memory_journal", entity_id=entry.id, recorded_at=entry.occurred_date)
        db.session.delete(entry); db.session.commit()
        warning = False
        try:
            if path: path.unlink(missing_ok=True)
            else: warning = True
        except OSError:
            warning = True
        return jsonify({"success": True, "file_cleanup": "warning" if warning else "ok"})
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Data tidak valid"}), 400
    before = snapshot_fields(entry, "memory_journal")
    if "occurred_date" in data:
        parsed = _parse_date(data.get("occurred_date"))
        if not parsed: return jsonify({"error": "Tanggal momen tidak valid"}), 400
        entry.occurred_date = parsed
    if "caption" in data:
        caption = (data.get("caption") or "").strip() or None
        if caption and len(caption) > 500: return jsonify({"error": "Caption maksimal 500 karakter"}), 400
        entry.caption = caption
    entry.updated_at = now_wib()
    changed = diff_snapshots(before, snapshot_fields(entry, "memory_journal"), "memory_journal")
    if changed:
        record_audit_event(child_id=entry.child_id, actor_user_id=user_id, action="update",
            entity_type="memory_journal", entity_id=entry.id, changed_fields=changed,
            recorded_at=entry.occurred_date)
        db.session.commit()
    return jsonify(_serialize(entry, role, user_id))


@memory_journal_bp.route("/memory-journal/<int:entry_id>/photo", methods=["GET"])
def photo(entry_id):
    entry = db.session.get(MemoryJournalEntry, entry_id)
    user_id = get_current_user_id()
    if not entry or not user_id or not get_accessible_child(entry.child_id, user_id):
        return jsonify({"error": "Foto tidak ditemukan"}), 404
    path = validated_journal_path(entry.photo_filename)
    if not path or not path.is_file():
        return jsonify({"error": "Foto tidak ditemukan"}), 404
    return send_file(path, mimetype="image/webp", max_age=3600, conditional=True)
