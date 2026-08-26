"""
Endpoint BACA SAJA buat Caregiver Audit Trail (Phase 1) — lihat
backend/docs/AUDIT_TRAIL.md buat kontrak lengkapnya.

SENGAJA TIDAK ADA endpoint POST/PUT/DELETE buat audit event di sini sama
sekali — baris caregiver_audit_events CUMA pernah dibikin lewat
utils/audit.py:record_audit_event(), dipanggil dari DALAM route
create/update/delete entity-nya sendiri (lihat routes/daily_log_routes.py
dkk), TIDAK PERNAH dari input klien langsung.
"""
from flask import Blueprint, request, jsonify

from models import CaregiverAuditEvent
from utils.access import get_accessible_child
from utils.auth import get_current_user_id
from utils.audit import ACTIONS, ALL_ENTITY_TYPES

audit_bp = Blueprint("audit", __name__)

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


def _parse_positive_int(raw, field_name):
    """Balikin (value, error_response_atau_None). value None kalau raw None (parameter opsional nggak dikasih)."""
    if raw is None:
        return None, None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, (jsonify({"error": f"{field_name} tidak valid"}), 400)
    if value < 1:
        return None, (jsonify({"error": f"{field_name} tidak valid"}), 400)
    return value, None


@audit_bp.route("/children/<int:child_id>/audit-events", methods=["GET"])
def list_audit_events(child_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    # Sama persis pola akses endpoint lain — 404 generik buat anak yang
    # nggak ada ATAU nggak bisa diakses user ini, biar user yang nggak
    # berwenang nggak bisa mbedain "anak ini nggak ada" dari "anak ini
    # ada tapi kamu nggak punya akses" (apalagi "audit event-nya ada").
    child = get_accessible_child(child_id, user_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    limit_raw = request.args.get("limit", str(DEFAULT_LIMIT))
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "limit tidak valid"}), 400
    if limit < 1 or limit > MAX_LIMIT:
        return jsonify({"error": f"limit harus antara 1 dan {MAX_LIMIT}"}), 400

    cursor_id, err = _parse_positive_int(request.args.get("cursor"), "cursor")
    if err:
        return err

    action = request.args.get("action")
    if action is not None and action not in ACTIONS:
        return jsonify({"error": f"action harus salah satu dari: {', '.join(ACTIONS)}"}), 400

    entity_type = request.args.get("entity_type")
    if entity_type is not None and entity_type not in ALL_ENTITY_TYPES:
        return jsonify({"error": f"entity_type harus salah satu dari: {', '.join(ALL_ENTITY_TYPES)}"}), 400

    actor_filter, err = _parse_positive_int(request.args.get("actor_user_id"), "actor_user_id")
    if err:
        return err

    # SEMUA filter di bawah lewat SQLAlchemy query builder (parameterized)
    # — TIDAK PERNAH nyusun/interpolasi string SQL mentah dari input.
    query = CaregiverAuditEvent.query.filter(CaregiverAuditEvent.child_id == child_id)
    if action is not None:
        query = query.filter(CaregiverAuditEvent.action == action)
    if entity_type is not None:
        query = query.filter(CaregiverAuditEvent.entity_type == entity_type)
    if actor_filter is not None:
        query = query.filter(CaregiverAuditEvent.actor_user_id == actor_filter)
    if cursor_id is not None:
        # keyset pagination lewat id (bukan OFFSET) — id CaregiverAuditEvent
        # monoton naik SESUAI urutan dibikin, jadi "id < cursor" = "lebih
        # lama dari halaman sebelumnya", stabil walau ada event baru masuk
        # di antara 2 permintaan halaman (beda dari OFFSET yang bisa
        # dobel/kelewat kalau datanya berubah di tengah paginasi).
        query = query.filter(CaregiverAuditEvent.id < cursor_id)

    # ambil 1 ekstra buat tau apa masih ada halaman berikutnya, tanpa
    # query COUNT(*) terpisah
    rows = query.order_by(CaregiverAuditEvent.id.desc()).limit(limit + 1).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].id if has_more and rows else None

    return jsonify({
        "events": [r.to_dict() for r in rows],
        "next_cursor": next_cursor,
    })
