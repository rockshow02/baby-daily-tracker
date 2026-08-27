import re
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file

from extensions import db
from models import MemoryJournalEntry
from utils.access import WRITE_ROLES, get_accessible_child, resolve_role
from utils.audit import MONTHLY_STORY_PDF_EXPORT_ENTITY_TYPE, record_audit_event
from utils.auth import get_current_user_id
from utils.memory_journal_images import validated_journal_path
from utils.monthly_story import MonthlyStoryValidationError, build_monthly_story, validate_payload
from utils.monthly_story_pdf import render_monthly_story_pdf
from utils.monthly_story_snapshot import (decode_story_token, generate_story_token, story_digest)
from utils.snapshot_token import (SnapshotTokenInvalidError, SnapshotTokenUnauthorizedError,
                                  digests_match)
from utils.timezone_utils import now_wib, today_wib

monthly_story_bp = Blueprint("monthly_story", __name__)
MAX_BODY_BYTES = 20_000


def _child_context(child_id):
    user_id = get_current_user_id()
    child = get_accessible_child(child_id, user_id) if user_id else None
    if not user_id: return None, None, None, (jsonify({"error": "Belum login"}), 401)
    if not child: return user_id, None, None, (jsonify({"error": "Anak tidak ditemukan"}), 404)
    role = resolve_role(child, user_id)
    return user_id, child, role, None


def _body():
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        return None, (jsonify({"error": "Ukuran permintaan terlalu besar"}), 413)
    raw = request.stream.read(MAX_BODY_BYTES + 1)
    if len(raw) > MAX_BODY_BYTES:
        return None, (jsonify({"error": "Ukuran permintaan terlalu besar"}), 413)
    request._cached_data = raw
    data = request.get_json(silent=True)
    return (data, None) if isinstance(data, dict) else (None, (jsonify({"error": "Format data tidak valid"}), 400))


def _validated(data, role, today):
    try:
        return validate_payload(data, today, role in WRITE_ROLES), None
    except PermissionError as exc:
        return None, (jsonify({"error": str(exc)}), 403)
    except MonthlyStoryValidationError as exc:
        return None, (jsonify({"error": str(exc)}), 400)


def _public_report(report):
    """Checksum file hanya untuk digest server; jangan kirim field teknis ke UI."""
    return {**report, "selected_photos": [
        {key: value for key, value in item.items() if key != "_content_sha256"}
        for item in report["selected_photos"]
    ]}


@monthly_story_bp.route("/children/<int:child_id>/monthly-story/preview", methods=["POST"])
def preview(child_id):
    user_id, child, role, error = _child_context(child_id)
    if error: return error
    data, error = _body()
    if error: return error
    parsed, error = _validated(data, role, today_wib())
    if error: return error
    now = now_wib()
    try:
        report = build_monthly_story(child, *parsed, generated_at=now)
    except MonthlyStoryValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    token = generate_story_token(child_id, user_id, now.isoformat(), story_digest(report))
    return jsonify({**_public_report(report), "snapshot_token": token,
                    "capabilities": {"can_preview": True, "can_export": role in WRITE_ROLES,
                                     "can_add_note": role in WRITE_ROLES}})


@monthly_story_bp.route("/children/<int:child_id>/monthly-story/pdf", methods=["POST"])
def pdf(child_id):
    user_id, child, role, error = _child_context(child_id)
    if error: return error
    if role not in WRITE_ROLES:
        return jsonify({"error": "Peran Anda tidak bisa mengunduh cerita bulanan"}), 403
    data, error = _body()
    if error: return error
    parsed, error = _validated(data, role, today_wib())
    if error: return error
    token = data.get("snapshot_token")
    if not isinstance(token, str) or not token:
        return jsonify({"error": "Buat pratinjau ulang sebelum mengunduh PDF"}), 400
    try:
        claims = decode_story_token(token, child_id, user_id)
    except SnapshotTokenUnauthorizedError:
        return jsonify({"error": "Token pratinjau tidak berlaku untuk pengguna ini"}), 403
    except SnapshotTokenInvalidError:
        return jsonify({"error": "Token pratinjau tidak valid atau sudah kedaluwarsa"}), 400
    try:
        preview_at = datetime.fromisoformat(claims["preview_at"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Token pratinjau tidak valid atau sudah kedaluwarsa"}), 400
    try:
        report = build_monthly_story(child, *parsed, generated_at=preview_at)
    except MonthlyStoryValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    if not digests_match(story_digest(report), claims.get("digest")):
        return jsonify({"error": "Data cerita berubah. Buat pratinjau ulang sebelum mengunduh PDF"}), 409
    photo_paths = {}
    for item in report["selected_photos"]:
        entry = db.session.get(MemoryJournalEntry, item["id"])
        path = validated_journal_path(entry.photo_filename) if entry else None
        if path and path.is_file(): photo_paths[item["id"]] = path
    buffer = render_monthly_story_pdf(report, photo_paths)
    record_audit_event(child_id=child_id, actor_user_id=user_id, action="create",
        entity_type=MONTHLY_STORY_PDF_EXPORT_ENTITY_TYPE, entity_id=0)
    db.session.commit()
    safe_name = re.sub(r"[^a-z0-9-]+", "-", (child.nickname or child.name).lower()).strip("-") or "anak"
    return send_file(buffer, mimetype="application/pdf", as_attachment=True,
                     download_name=f"cerita-{safe_name}-{report['month']}.pdf")
