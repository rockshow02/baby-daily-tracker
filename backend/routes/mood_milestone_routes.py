from datetime import datetime

from flask import Blueprint, request, jsonify, session

from extensions import db
from models import Child, MoodLog, MilestoneLog, User
from utils.telegram import notify_other_caregivers
from utils.access import get_accessible_child, resolve_role, can_delete_record, WRITE_ROLES
from utils.auth import get_current_user_id
from utils.timezone_utils import now_wib, to_wib_naive
from utils.milestone_reference import evaluate_milestone, MILESTONE_REFERENCE
from utils.audit import record_audit_event, snapshot_fields, diff_snapshots

mood_milestone_bp = Blueprint("mood_milestone", __name__)

VALID_MOODS = {"ceria", "baik", "sedih", "menangis"}
VALID_MILESTONE_TYPES = set(MILESTONE_REFERENCE.keys()) | {"custom"}

NO_WRITE_ROLE_MESSAGE = "Peran Anda hanya bisa melihat data, tidak bisa menambah/mengubah catatan."
NO_DELETE_PERMISSION_MESSAGE = "Anda tidak punya izin untuk menghapus catatan ini."


def _owned_child(child_id):
    user_id = get_current_user_id()
    if not user_id:
        return None
    return get_accessible_child(child_id, user_id)


# ---------- MOOD ----------

@mood_milestone_bp.route("/children/<int:child_id>/mood-logs", methods=["GET"])
def list_mood_logs(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    date_str = request.args.get("date")
    query = MoodLog.query.filter_by(child_id=child_id)
    if date_str:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        query = query.filter(db.func.date(MoodLog.timestamp) == target_date)

    logs = query.order_by(MoodLog.timestamp.desc()).limit(200).all()
    return jsonify([log.to_dict() for log in logs])


@mood_milestone_bp.route("/children/<int:child_id>/mood-logs", methods=["POST"])
def create_mood_log(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    user_id = get_current_user_id()
    if resolve_role(child, user_id) not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    data = request.get_json() or {}
    mood = data.get("mood")
    if mood not in VALID_MOODS:
        return jsonify({"error": f"mood harus salah satu dari: {', '.join(VALID_MOODS)}"}), 400

    log = MoodLog(
        created_by_user_id=user_id,
        child_id=child_id,
        timestamp=to_wib_naive(data["timestamp"]) if data.get("timestamp") else now_wib(),
        mood=mood,
        notes=data.get("notes"),
    )
    db.session.add(log)
    db.session.flush()
    record_audit_event(
        child_id=child_id, actor_user_id=user_id, action="create",
        entity_type="mood_log", entity_id=log.id, recorded_at=log.timestamp,
    )
    db.session.commit()
    notify_other_caregivers(child, user_id, f"😊 {User.query.get(user_id).name} mencatat mood untuk {child.nickname or child.name}.")
    return jsonify(log.to_dict()), 201


@mood_milestone_bp.route("/mood-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_mood_log(log_id):
    log = MoodLog.query.get_or_404(log_id)
    child = _owned_child(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    user_id = get_current_user_id()
    role = resolve_role(child, user_id)

    if request.method == "DELETE":
        if not can_delete_record(role, log.created_by_user_id, user_id):
            return jsonify({"error": NO_DELETE_PERMISSION_MESSAGE}), 403
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="delete",
            entity_type="mood_log", entity_id=log.id, recorded_at=log.timestamp,
        )
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    if role not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    data = request.get_json() or {}
    before = snapshot_fields(log, "mood_log")
    if "timestamp" in data:
        log.timestamp = to_wib_naive(data["timestamp"])
    if "mood" in data:
        if data["mood"] not in VALID_MOODS:
            return jsonify({"error": f"mood harus salah satu dari: {', '.join(VALID_MOODS)}"}), 400
        log.mood = data["mood"]
    if "notes" in data:
        log.notes = data["notes"]
    changed = diff_snapshots(before, snapshot_fields(log, "mood_log"), "mood_log")
    if changed:
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="update",
            entity_type="mood_log", entity_id=log.id, changed_fields=changed, recorded_at=log.timestamp,
        )
    db.session.commit()
    return jsonify(log.to_dict())


# ---------- MILESTONE ----------

def _age_months_at(birth_date, on_date):
    days = (on_date - birth_date).days
    return days / 30.4375


@mood_milestone_bp.route("/children/<int:child_id>/milestone-logs", methods=["GET"])
def list_milestone_logs(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    logs = (
        MilestoneLog.query.filter_by(child_id=child_id)
        .order_by(MilestoneLog.achieved_date.desc())
        .all()
    )
    result = []
    for log in logs:
        data = log.to_dict()
        age_months = _age_months_at(child.birth_date, log.achieved_date)
        data["age_months"] = round(age_months, 1)
        data["evaluation"] = evaluate_milestone(log.milestone_type, age_months)
        result.append(data)
    return jsonify(result)


@mood_milestone_bp.route("/children/<int:child_id>/milestone-logs", methods=["POST"])
def create_milestone_log(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    user_id = get_current_user_id()
    if resolve_role(child, user_id) not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    data = request.get_json() or {}
    milestone_type = data.get("milestone_type")
    if milestone_type not in VALID_MILESTONE_TYPES:
        return jsonify({"error": f"milestone_type harus salah satu dari: {', '.join(VALID_MILESTONE_TYPES)}"}), 400
    if milestone_type == "custom" and not data.get("custom_label"):
        return jsonify({"error": "custom_label wajib diisi untuk milestone custom"}), 400
    if not data.get("achieved_date"):
        return jsonify({"error": "achieved_date wajib diisi"}), 400

    achieved_date = datetime.strptime(data["achieved_date"], "%Y-%m-%d").date()

    log = MilestoneLog(
        created_by_user_id=user_id,
        child_id=child_id,
        milestone_type=milestone_type,
        custom_label=data.get("custom_label") if milestone_type == "custom" else None,
        achieved_date=achieved_date,
        notes=data.get("notes"),
    )
    db.session.add(log)
    db.session.flush()
    record_audit_event(
        child_id=child_id, actor_user_id=user_id, action="create",
        entity_type="milestone_log", entity_id=log.id, recorded_at=log.achieved_date,
    )
    db.session.commit()
    notify_other_caregivers(child, user_id, f"✨ {User.query.get(user_id).name} mencatat momen penting untuk {child.nickname or child.name}.")

    result = log.to_dict()
    age_months = _age_months_at(child.birth_date, achieved_date)
    result["age_months"] = round(age_months, 1)
    result["evaluation"] = evaluate_milestone(milestone_type, age_months)
    return jsonify(result), 201


@mood_milestone_bp.route("/milestone-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_milestone_log(log_id):
    log = MilestoneLog.query.get_or_404(log_id)
    child = _owned_child(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    user_id = get_current_user_id()
    role = resolve_role(child, user_id)

    if request.method == "DELETE":
        if not can_delete_record(role, log.created_by_user_id, user_id):
            return jsonify({"error": NO_DELETE_PERMISSION_MESSAGE}), 403
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="delete",
            entity_type="milestone_log", entity_id=log.id, recorded_at=log.achieved_date,
        )
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    if role not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    data = request.get_json() or {}
    before = snapshot_fields(log, "milestone_log")
    if "milestone_type" in data:
        if data["milestone_type"] not in VALID_MILESTONE_TYPES:
            return jsonify({"error": f"milestone_type harus salah satu dari: {', '.join(VALID_MILESTONE_TYPES)}"}), 400
        log.milestone_type = data["milestone_type"]
    if "custom_label" in data:
        log.custom_label = data["custom_label"] if log.milestone_type == "custom" else None
    if "achieved_date" in data:
        log.achieved_date = datetime.strptime(data["achieved_date"], "%Y-%m-%d").date()
    if "notes" in data:
        log.notes = data["notes"]
    changed = diff_snapshots(before, snapshot_fields(log, "milestone_log"), "milestone_log")
    if changed:
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="update",
            entity_type="milestone_log", entity_id=log.id, changed_fields=changed, recorded_at=log.achieved_date,
        )
    db.session.commit()

    result = log.to_dict()
    age_months = _age_months_at(child.birth_date, log.achieved_date)
    result["age_months"] = round(age_months, 1)
    result["evaluation"] = evaluate_milestone(log.milestone_type, age_months)
    return jsonify(result)


@mood_milestone_bp.route("/milestone-reference", methods=["GET"])
def milestone_reference():
    """Daftar tipe milestone standar + acuannya, buat ditampilkan di form."""
    return jsonify(MILESTONE_REFERENCE)