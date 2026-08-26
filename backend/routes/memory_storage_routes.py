from flask import Blueprint, current_app, jsonify, request

from extensions import db
from models import MemoryJournalEntry
from utils.access import ROLE_OWNER, get_accessible_child, resolve_role
from utils.audit import MEMORY_JOURNAL_PHOTO_OPTIMIZED_ENTITY_TYPE, record_audit_event
from utils.auth import get_current_user_id
from utils.memory_journal_images import validated_journal_path
from utils.memory_storage import optimize_photo_file, safe_child_files

memory_storage_bp = Blueprint("memory_storage", __name__)
DEFAULT_WARNING_BYTES = 100 * 1024 * 1024


def _owner(child_id):
    user_id = get_current_user_id()
    child = get_accessible_child(child_id, user_id) if user_id else None
    if not user_id: return None, None, (jsonify({"error": "Belum login"}), 401)
    if not child: return user_id, None, (jsonify({"error": "Anak tidak ditemukan"}), 404)
    if resolve_role(child, user_id) != ROLE_OWNER:
        return user_id, child, (jsonify({"error": "Hanya pemilik yang dapat mengelola penyimpanan foto"}), 403)
    return user_id, child, None


def _snapshot(child_id):
    entries = MemoryJournalEntry.query.filter_by(child_id=child_id).all()
    names = {entry.photo_filename for entry in entries}
    disk = safe_child_files(child_id)
    disk_by_name = {path.name: path for path in disk}
    missing = [entry for entry in entries if entry.photo_filename not in disk_by_name]
    orphans = [path for path in disk if path.name not in names]
    largest = []
    for entry in entries:
        path = disk_by_name.get(entry.photo_filename)
        if path:
            largest.append({"id": entry.id, "caption": entry.caption,
                            "occurred_date": entry.occurred_date.isoformat(),
                            "size_bytes": path.stat().st_size})
    largest.sort(key=lambda item: item["size_bytes"], reverse=True)
    actual = sum(item["size_bytes"] for item in largest)
    warning_at = int(current_app.config.get("MEMORY_JOURNAL_WARNING_BYTES", DEFAULT_WARNING_BYTES))
    return {"photo_count": len(entries), "actual_bytes": actual, "warning_bytes": warning_at,
            "usage_percent": round(actual / warning_at * 100, 1) if warning_at > 0 else None,
            "warning": actual >= warning_at, "missing_file_count": len(missing),
            "missing_entries": [{"id": x.id, "occurred_date": x.occurred_date.isoformat()} for x in missing],
            "orphan_file_count": len(orphans), "orphan_bytes": sum(x.stat().st_size for x in orphans),
            "largest": largest[:10]}, orphans


@memory_storage_bp.route("/children/<int:child_id>/memory-storage", methods=["GET"])
def overview(child_id):
    _user_id, _child, error = _owner(child_id)
    if error: return error
    result, _orphans = _snapshot(child_id)
    return jsonify(result)


@memory_storage_bp.route("/children/<int:child_id>/memory-storage/cleanup", methods=["POST"])
def cleanup(child_id):
    _user_id, _child, error = _owner(child_id)
    if error: return error
    data = request.get_json(silent=True)
    if not isinstance(data, dict): return jsonify({"error": "Format data tidak valid"}), 400
    apply = data.get("apply") is True
    if apply and data.get("confirmation") != "BERSIHKAN":
        return jsonify({"error": "Ketik BERSIHKAN untuk menerapkan pembersihan"}), 400
    before, orphans = _snapshot(child_id)
    deleted = 0; deleted_bytes = 0
    if apply:
        # Revalidasi setiap kandidat sesaat sebelum unlink. Hanya regular file,
        # bukan symlink, dan tetap orphan pada snapshot database terkini.
        current_names = {name for (name,) in db.session.query(MemoryJournalEntry.photo_filename).filter_by(child_id=child_id).all()}
        for candidate in orphans:
            if candidate.name in current_names or candidate.is_symlink() or not candidate.is_file():
                continue
            safe = validated_journal_path(candidate.name)
            if safe != candidate.resolve() or safe.parent != candidate.parent.resolve():
                continue
            try:
                size = candidate.stat().st_size
                candidate.unlink()
                deleted += 1; deleted_bytes += size
            except OSError:
                return jsonify({"error": "Pembersihan berhenti karena satu file tidak dapat dihapus",
                    "applied": True, "deleted_count": deleted, "deleted_bytes": deleted_bytes}), 409
    return jsonify({"applied": apply, "would_delete_count": before["orphan_file_count"],
                    "would_delete_bytes": before["orphan_bytes"], "deleted_count": deleted,
                    "deleted_bytes": deleted_bytes})


@memory_storage_bp.route("/children/<int:child_id>/memory-storage/<int:entry_id>/optimize", methods=["POST"])
def optimize(child_id, entry_id):
    user_id, _child, error = _owner(child_id)
    if error: return error
    entry = db.session.get(MemoryJournalEntry, entry_id)
    if not entry or entry.child_id != child_id:
        return jsonify({"error": "Foto tidak ditemukan"}), 404
    try:
        before, after, width, height, changed = optimize_photo_file(entry.photo_filename)
    except (OSError, ValueError):
        return jsonify({"error": "Foto tidak dapat dioptimalkan dengan aman"}), 409
    if changed:
        entry.photo_size_bytes = after; entry.photo_width = width; entry.photo_height = height
        record_audit_event(child_id=child_id, actor_user_id=user_id, action="create",
            entity_type=MEMORY_JOURNAL_PHOTO_OPTIMIZED_ENTITY_TYPE, entity_id=entry.id)
        db.session.commit()
    return jsonify({"changed": changed, "before_bytes": before, "after_bytes": after,
                    "saved_bytes": before - after})
