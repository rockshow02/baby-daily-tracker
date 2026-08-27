from datetime import date

from flask import Blueprint, jsonify, request, send_file

from extensions import db
from models import MemoryJournalEntry, MemoryJournalMetadata, MemoryJournalTag
from sqlalchemy import or_
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
                is_favorite=bool(entry.metadata_record and entry.metadata_record.is_favorite),
                tags=sorted(tag.tag for tag in entry.tag_records),
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
        query = MemoryJournalEntry.query.filter_by(child_id=child_id)
        search = (request.args.get("q") or "").strip()
        tag = (request.args.get("tag") or "").strip().casefold()
        if search:
            safe_search = search.replace("%", r"\%").replace("_", r"\_")
            pattern = f"%{safe_search}%"
            query = query.filter(or_(
                MemoryJournalEntry.caption.ilike(pattern, escape="\\"),
                MemoryJournalEntry.tag_records.any(MemoryJournalTag.tag.ilike(pattern, escape="\\")),
            ))
        if tag:
            query = query.join(MemoryJournalTag).filter(MemoryJournalTag.tag == tag)
        if request.args.get("favorite") == "true":
            query = query.join(MemoryJournalMetadata).filter(MemoryJournalMetadata.is_favorite.is_(True))
        if request.args.get("created_by"):
            try: query = query.filter(MemoryJournalEntry.created_by_user_id == int(request.args["created_by"]))
            except ValueError: return jsonify({"error": "Filter pembuat tidak valid"}), 400
        for key, column, operator in (("from", MemoryJournalEntry.occurred_date, lambda c,v:c>=v),
                                      ("to", MemoryJournalEntry.occurred_date, lambda c,v:c<=v)):
            if request.args.get(key):
                parsed = _parse_date(request.args[key])
                if not parsed: return jsonify({"error": "Filter tanggal tidak valid"}), 400
                query = query.filter(operator(column, parsed))
        ascending = request.args.get("sort") == "oldest"
        order = (MemoryJournalEntry.occurred_date.asc(), MemoryJournalEntry.id.asc()) if ascending else (MemoryJournalEntry.occurred_date.desc(), MemoryJournalEntry.id.desc())
        entries = query.order_by(*order).limit(100).all()
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
    manual_changed = []
    if "occurred_date" in data:
        parsed = _parse_date(data.get("occurred_date"))
        if not parsed: return jsonify({"error": "Tanggal momen tidak valid"}), 400
        entry.occurred_date = parsed
    if "caption" in data:
        caption = (data.get("caption") or "").strip() or None
        if caption and len(caption) > 500: return jsonify({"error": "Caption maksimal 500 karakter"}), 400
        entry.caption = caption
    if "is_favorite" in data:
        if type(data["is_favorite"]) is not bool:
            return jsonify({"error": "Nilai favorit tidak valid"}), 400
        metadata = entry.metadata_record
        old_favorite = bool(metadata and metadata.is_favorite)
        if old_favorite != data["is_favorite"]:
            if metadata is None:
                metadata = MemoryJournalMetadata(entry=entry)
                db.session.add(metadata)
            metadata.is_favorite = data["is_favorite"]
            manual_changed.append("is_favorite")
    if "tags" in data:
        raw_tags = data["tags"]
        if not isinstance(raw_tags, list) or len(raw_tags) > 5:
            return jsonify({"error": "Tag harus berupa daftar maksimal 5 item"}), 400
        tags = []
        for value in raw_tags:
            if not isinstance(value, str): return jsonify({"error": "Tag tidak valid"}), 400
            normalized = " ".join(value.strip().casefold().split())
            if not normalized or len(normalized) > 30: return jsonify({"error": "Setiap tag harus 1-30 karakter"}), 400
            if normalized not in tags: tags.append(normalized)
        old_tags = sorted(tag.tag for tag in entry.tag_records)
        if sorted(tags) != old_tags:
            for record in list(entry.tag_records): db.session.delete(record)
            for value in tags: db.session.add(MemoryJournalTag(entry=entry, tag=value))
            manual_changed.append("private_details")
    entry.updated_at = now_wib()
    changed = diff_snapshots(before, snapshot_fields(entry, "memory_journal"), "memory_journal") + manual_changed
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
