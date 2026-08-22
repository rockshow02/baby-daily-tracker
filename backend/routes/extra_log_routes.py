from flask import Blueprint, request, jsonify, session

from extensions import db
from models import Child, PumpingLog, ActivityLog, User
from utils.telegram import notify_other_caregivers
from utils.access import get_accessible_child
from utils.auth import get_current_user_id
from utils.idempotency import idempotent_create, compute_fingerprint
from utils.timezone_utils import now_wib, today_wib, to_wib_naive
from utils.audit import record_audit_event, snapshot_fields, diff_snapshots

extra_log_bp = Blueprint("extra_log", __name__)

ACTIVITY_TYPES = {"stroll", "bathing"}


def _get_owned_child_or_none(child_id):
    user_id = get_current_user_id()
    if not user_id:
        return None
    return get_accessible_child(child_id, user_id)


def _parse_date_param():
    date_str = request.args.get("date")
    if date_str:
        from datetime import datetime
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    return today_wib()


# ---------- PUMPING (Perah ASI) ----------

@extra_log_bp.route("/children/<int:child_id>/pumping-logs", methods=["GET"])
def list_pumping_logs(child_id):
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    target_date = _parse_date_param()
    logs = (
        PumpingLog.query.filter(
            PumpingLog.child_id == child_id,
            db.func.date(PumpingLog.timestamp) == target_date,
        )
        .order_by(PumpingLog.timestamp.desc())
        .all()
    )
    return jsonify([log.to_dict() for log in logs])


@extra_log_bp.route("/children/<int:child_id>/pumping-logs", methods=["POST"])
def create_pumping_log(child_id):
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    data = request.get_json() or {}
    user_id = get_current_user_id()
    client_request_id = request.headers.get("X-Idempotency-Key")
    fingerprint = compute_fingerprint(data)

    def build():
        log = PumpingLog(
            created_by_user_id=user_id,
            child_id=child_id,
            timestamp=to_wib_naive(data["timestamp"]) if data.get("timestamp") else now_wib(),
            duration_minutes=data.get("duration_minutes"),
            volume_ml=data.get("volume_ml"),
            breast_side=data.get("breast_side"),
            notes=data.get("notes"),
        )
        db.session.add(log)
        db.session.flush()
        record_audit_event(
            child_id=child_id, actor_user_id=user_id, action="create",
            entity_type="pumping_log", entity_id=log.id, recorded_at=log.timestamp,
        )
        return log.to_dict()

    def send_notification():
        notify_other_caregivers(child, user_id, f"🍼 {User.query.get(user_id).name} mencatat perah ASI untuk {child.nickname or child.name}.")

    body, status, _ = idempotent_create(
        user_id, child_id, "pumping-logs", client_request_id, fingerprint, build, after_commit=send_notification
    )
    return jsonify(body), status


@extra_log_bp.route("/pumping-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_pumping_log(log_id):
    log = PumpingLog.query.get_or_404(log_id)
    child = _get_owned_child_or_none(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    user_id = get_current_user_id()

    if request.method == "DELETE":
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="delete",
            entity_type="pumping_log", entity_id=log.id, recorded_at=log.timestamp,
        )
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
    before = snapshot_fields(log, "pumping_log")
    if "timestamp" in data:
        log.timestamp = to_wib_naive(data["timestamp"])
    if "duration_minutes" in data:
        log.duration_minutes = data["duration_minutes"]
    if "volume_ml" in data:
        log.volume_ml = data["volume_ml"]
    if "breast_side" in data:
        log.breast_side = data["breast_side"]
    if "notes" in data:
        log.notes = data["notes"]
    changed = diff_snapshots(before, snapshot_fields(log, "pumping_log"))
    if changed:
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="update",
            entity_type="pumping_log", entity_id=log.id, changed_fields=changed, recorded_at=log.timestamp,
        )
    db.session.commit()
    return jsonify(log.to_dict())


# ---------- ACTIVITY (Jalan-jalan, Mandi) ----------

@extra_log_bp.route("/children/<int:child_id>/activity-logs", methods=["GET"])
def list_activity_logs(child_id):
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    target_date = _parse_date_param()
    query = ActivityLog.query.filter(
        ActivityLog.child_id == child_id,
        db.func.date(ActivityLog.timestamp) == target_date,
    )
    activity_type = request.args.get("activity_type")
    if activity_type:
        query = query.filter(ActivityLog.activity_type == activity_type)

    logs = query.order_by(ActivityLog.timestamp.desc()).all()
    return jsonify([log.to_dict() for log in logs])


@extra_log_bp.route("/children/<int:child_id>/activity-logs", methods=["POST"])
def create_activity_log(child_id):
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    data = request.get_json() or {}
    activity_type = data.get("activity_type")
    if activity_type not in ACTIVITY_TYPES:
        return jsonify({"error": f"activity_type harus salah satu dari: {', '.join(ACTIVITY_TYPES)}"}), 400

    user_id = get_current_user_id()
    client_request_id = request.headers.get("X-Idempotency-Key")
    fingerprint = compute_fingerprint(data)

    def build():
        log = ActivityLog(
            created_by_user_id=user_id,
            child_id=child_id,
            activity_type=activity_type,
            timestamp=to_wib_naive(data["timestamp"]) if data.get("timestamp") else now_wib(),
            duration_minutes=data.get("duration_minutes"),
            notes=data.get("notes"),
        )
        db.session.add(log)
        db.session.flush()
        record_audit_event(
            child_id=child_id, actor_user_id=user_id, action="create",
            entity_type="activity_log", entity_id=log.id, recorded_at=log.timestamp,
        )
        return log.to_dict()

    def send_notification():
        notify_other_caregivers(child, user_id, f"🚶 {User.query.get(user_id).name} mencatat aktivitas untuk {child.nickname or child.name}.")

    body, status, _ = idempotent_create(
        user_id, child_id, "activity-logs", client_request_id, fingerprint, build, after_commit=send_notification
    )
    return jsonify(body), status


@extra_log_bp.route("/activity-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_activity_log(log_id):
    log = ActivityLog.query.get_or_404(log_id)
    child = _get_owned_child_or_none(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    user_id = get_current_user_id()

    if request.method == "DELETE":
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="delete",
            entity_type="activity_log", entity_id=log.id, recorded_at=log.timestamp,
        )
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
    before = snapshot_fields(log, "activity_log")
    if "timestamp" in data:
        log.timestamp = to_wib_naive(data["timestamp"])
    if "activity_type" in data:
        if data["activity_type"] not in ACTIVITY_TYPES:
            return jsonify({"error": f"activity_type harus salah satu dari: {', '.join(ACTIVITY_TYPES)}"}), 400
        log.activity_type = data["activity_type"]
    if "duration_minutes" in data:
        log.duration_minutes = data["duration_minutes"]
    if "notes" in data:
        log.notes = data["notes"]
    changed = diff_snapshots(before, snapshot_fields(log, "activity_log"))
    if changed:
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="update",
            entity_type="activity_log", entity_id=log.id, changed_fields=changed, recorded_at=log.timestamp,
        )
    db.session.commit()
    return jsonify(log.to_dict())