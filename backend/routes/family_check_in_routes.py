"""Refleksi perkembangan bulanan keluarga, tanpa penilaian klinis."""
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import DevelopmentGoal, FamilyDevelopmentCheckIn
from utils.access import WRITE_ROLES, can_delete_record, get_accessible_child, resolve_role
from utils.audit import diff_snapshots, record_audit_event, snapshot_fields
from utils.auth import get_current_user_id

family_check_in_bp = Blueprint("family_check_in", __name__)
AREA_KEYS = ("motor", "communication", "social", "sleep", "nutrition")
AREA_STATES = {"noticed", "exploring", "not_checked"}
DISCLAIMER = ("Check-in ini adalah refleksi keluarga, bukan skrining, diagnosis, atau penilaian "
              "apakah perkembangan anak normal atau terlambat.")


def _context(child_id):
    user_id = get_current_user_id()
    child = get_accessible_child(child_id, user_id) if user_id else None
    return user_id, child


def _values(data, child_id):
    try:
        period = datetime.strptime(data.get("period_month", ""), "%Y-%m").date().replace(day=1)
    except (TypeError, ValueError):
        raise ValueError("Bulan check-in harus berformat YYYY-MM")
    raw_areas = data.get("areas")
    if not isinstance(raw_areas, dict) or set(raw_areas) - set(AREA_KEYS):
        raise ValueError("Area check-in tidak valid")
    areas = {key: raw_areas.get(key, "not_checked") for key in AREA_KEYS}
    if any(value not in AREA_STATES for value in areas.values()):
        raise ValueError("Pilihan refleksi tidak valid")
    note = data.get("reflection_note")
    if note is not None and not isinstance(note, str):
        raise ValueError("Catatan refleksi harus berupa teks")
    note = note.replace("\r\n", "\n").replace("\r", "\n").strip() if note else None
    if note and len(note) > 1000:
        raise ValueError("Catatan refleksi maksimal 1000 karakter")
    discuss = data.get("discuss_with_professional", False)
    if not isinstance(discuss, bool):
        raise ValueError("Pilihan diskusi harus ya atau tidak")
    goal_id = data.get("linked_goal_id")
    if goal_id is not None:
        if isinstance(goal_id, bool) or not isinstance(goal_id, int):
            raise ValueError("Tujuan yang ditautkan tidak valid")
        if not DevelopmentGoal.query.filter_by(id=goal_id, child_id=child_id).first():
            raise ValueError("Tujuan yang ditautkan tidak ditemukan")
    return {"period_month": period, "areas": areas, "reflection_note": note,
            "discuss_with_professional": discuss, "linked_goal_id": goal_id}


def _serialize(row, role, user_id):
    result = row.to_dict()
    result["can_edit"] = can_delete_record(role, row.created_by_user_id, user_id)
    result["can_delete"] = result["can_edit"]
    return result


@family_check_in_bp.route("/children/<int:child_id>/family-development-check-ins", methods=["GET", "POST"])
def collection(child_id):
    user_id, child = _context(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404
    role = resolve_role(child, user_id)
    if request.method == "GET":
        rows = (FamilyDevelopmentCheckIn.query.filter_by(child_id=child_id)
                .order_by(FamilyDevelopmentCheckIn.period_month.desc(), FamilyDevelopmentCheckIn.id.desc())
                .limit(120).all())
        goals = DevelopmentGoal.query.filter_by(child_id=child_id).order_by(DevelopmentGoal.target_date.desc()).limit(100).all()
        return jsonify({"items": [_serialize(row, role, user_id) for row in rows],
                        "goals": [{"id": goal.id, "title": goal.title} for goal in goals],
                        "can_create": role in WRITE_ROLES, "disclaimer": DISCLAIMER})
    if role not in WRITE_ROLES:
        return jsonify({"error": "Peran Anda hanya bisa melihat check-in"}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Format data tidak valid"}), 400
    try:
        values = _values(data, child_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    existing = FamilyDevelopmentCheckIn.query.filter_by(
        child_id=child_id, created_by_user_id=user_id, period_month=values["period_month"]).first()
    if existing:
        return jsonify({"error": "Anda sudah membuat check-in untuk bulan ini"}), 409
    row = FamilyDevelopmentCheckIn(child_id=child_id, created_by_user_id=user_id, **values)
    try:
        db.session.add(row); db.session.flush()
        record_audit_event(child_id=child_id, actor_user_id=user_id, action="create",
                           entity_type="family_development_check_in", entity_id=row.id,
                           recorded_at=row.period_month)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Anda sudah membuat check-in untuk bulan ini"}), 409
    return jsonify(_serialize(row, role, user_id)), 201


@family_check_in_bp.route("/family-development-check-ins/<int:check_in_id>", methods=["PUT", "DELETE"])
def item(check_in_id):
    row = db.session.get(FamilyDevelopmentCheckIn, check_in_id)
    if not row:
        return jsonify({"error": "Check-in tidak ditemukan"}), 404
    user_id, child = _context(row.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403
    role = resolve_role(child, user_id)
    if not can_delete_record(role, row.created_by_user_id, user_id):
        return jsonify({"error": "Anda tidak punya izin mengubah check-in ini"}), 403
    if request.method == "DELETE":
        record_audit_event(child_id=row.child_id, actor_user_id=user_id, action="delete",
                           entity_type="family_development_check_in", entity_id=row.id,
                           recorded_at=row.period_month)
        db.session.delete(row); db.session.commit()
        return jsonify({"success": True})
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Format data tidak valid"}), 400
    before = snapshot_fields(row, "family_development_check_in")
    try:
        values = _values(data, row.child_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    duplicate = FamilyDevelopmentCheckIn.query.filter(
        FamilyDevelopmentCheckIn.child_id == row.child_id,
        FamilyDevelopmentCheckIn.created_by_user_id == row.created_by_user_id,
        FamilyDevelopmentCheckIn.period_month == values["period_month"],
        FamilyDevelopmentCheckIn.id != row.id).first()
    if duplicate:
        return jsonify({"error": "Anda sudah membuat check-in untuk bulan ini"}), 409
    for key, value in values.items():
        setattr(row, key, value)
    changed = diff_snapshots(before, snapshot_fields(row, "family_development_check_in"),
                             "family_development_check_in")
    if changed:
        record_audit_event(child_id=row.child_id, actor_user_id=user_id, action="update",
                           entity_type="family_development_check_in", entity_id=row.id,
                           changed_fields=changed, recorded_at=row.period_month)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "Anda sudah membuat check-in untuk bulan ini"}), 409
    return jsonify(_serialize(row, role, user_id))
