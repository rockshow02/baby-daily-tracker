from datetime import date

from flask import Blueprint, jsonify, request

from extensions import db
from models import DevelopmentGoal
from utils.access import WRITE_ROLES, can_delete_record, get_accessible_child, resolve_role
from utils.audit import diff_snapshots, record_audit_event, snapshot_fields
from utils.auth import get_current_user_id
from utils.development_goal_engine import goal_state
from utils.timezone_utils import now_wib, today_wib

development_goal_bp = Blueprint("development_goal", __name__)
CATEGORIES = {"milestone", "growth_check", "routine", "custom"}


def _context(child_id):
    user_id = get_current_user_id(); child = get_accessible_child(child_id, user_id) if user_id else None
    return user_id, child


def _serialize(goal, role, user_id):
    data = goal.to_dict(); data["state"] = goal_state(goal, today_wib())
    data["can_edit"] = can_delete_record(role, goal.created_by_user_id, user_id)
    data["can_complete"] = role in WRITE_ROLES and goal.completed_at is None
    data["can_reopen"] = role in WRITE_ROLES and goal.completed_at is not None
    return data


def _values(data, partial=False):
    result = {}
    if not partial or "category" in data:
        if data.get("category") not in CATEGORIES: raise ValueError("Kategori tujuan tidak valid")
        result["category"] = data["category"]
    if not partial or "title" in data:
        title = (data.get("title") or "").strip()
        if not title or len(title) > 150: raise ValueError("Judul tujuan wajib diisi dan maksimal 150 karakter")
        result["title"] = title
    if not partial or "target_date" in data:
        try: result["target_date"] = date.fromisoformat(data.get("target_date") or "")
        except (TypeError, ValueError): raise ValueError("Tanggal target tidak valid")
    if not partial or "note" in data:
        note = (data.get("note") or "").strip() or None
        if note and len(note)>500: raise ValueError("Catatan maksimal 500 karakter")
        result["note"] = note
    return result


@development_goal_bp.route("/children/<int:child_id>/development-goals", methods=["GET", "POST"])
def collection(child_id):
    user_id, child = _context(child_id)
    if not child: return jsonify({"error":"Anak tidak ditemukan"}),404
    role=resolve_role(child,user_id)
    if request.method=="GET":
        goals=DevelopmentGoal.query.filter_by(child_id=child_id).order_by(DevelopmentGoal.target_date,DevelopmentGoal.id).limit(200).all()
        return jsonify({"items":[_serialize(x,role,user_id) for x in goals],"can_create":role in WRITE_ROLES,
                        "disclaimer":"Tujuan ini adalah rencana keluarga, bukan patokan atau penilaian medis."})
    if role not in WRITE_ROLES:return jsonify({"error":"Peran Anda hanya bisa melihat tujuan"}),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify({"error":"Format data tidak valid"}),400
    try: values=_values(data)
    except ValueError as exc:return jsonify({"error":str(exc)}),400
    goal=DevelopmentGoal(child_id=child_id,created_by_user_id=user_id,**values);db.session.add(goal);db.session.flush()
    record_audit_event(child_id=child_id,actor_user_id=user_id,action="create",entity_type="development_goal",entity_id=goal.id,recorded_at=goal.target_date)
    db.session.commit();return jsonify(_serialize(goal,role,user_id)),201


@development_goal_bp.route("/development-goals/<int:goal_id>",methods=["PUT","DELETE"])
def item(goal_id):
    goal=db.session.get(DevelopmentGoal,goal_id)
    if not goal:return jsonify({"error":"Tujuan tidak ditemukan"}),404
    user_id,child=_context(goal.child_id)
    if not child:return jsonify({"error":"Tidak diizinkan"}),403
    role=resolve_role(child,user_id)
    if not can_delete_record(role,goal.created_by_user_id,user_id):return jsonify({"error":"Anda tidak punya izin mengubah tujuan ini"}),403
    if request.method=="DELETE":
        record_audit_event(child_id=goal.child_id,actor_user_id=user_id,action="delete",entity_type="development_goal",entity_id=goal.id,recorded_at=goal.target_date)
        db.session.delete(goal);db.session.commit();return jsonify({"success":True})
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify({"error":"Format data tidak valid"}),400
    before=snapshot_fields(goal,"development_goal")
    try:
        for key,value in _values(data,partial=True).items():setattr(goal,key,value)
    except ValueError as exc:return jsonify({"error":str(exc)}),400
    changed=diff_snapshots(before,snapshot_fields(goal,"development_goal"),"development_goal")
    if changed:
        record_audit_event(child_id=goal.child_id,actor_user_id=user_id,action="update",entity_type="development_goal",entity_id=goal.id,changed_fields=changed,recorded_at=goal.target_date);db.session.commit()
    return jsonify(_serialize(goal,role,user_id))


@development_goal_bp.route("/development-goals/<int:goal_id>/<action>",methods=["POST"])
def change_state(goal_id,action):
    if action not in {"complete","reopen"}:return jsonify({"error":"Aksi tidak valid"}),404
    goal=db.session.get(DevelopmentGoal,goal_id)
    if not goal:return jsonify({"error":"Tujuan tidak ditemukan"}),404
    user_id,child=_context(goal.child_id);role=resolve_role(child,user_id) if child else None
    if role not in WRITE_ROLES:return jsonify({"error":"Peran Anda tidak bisa mengubah status tujuan"}),403
    should_complete=action=="complete"
    if (goal.completed_at is not None)==should_complete:return jsonify(_serialize(goal,role,user_id))
    before=snapshot_fields(goal,"development_goal")
    goal.completed_at=now_wib() if should_complete else None;goal.completed_by_user_id=user_id if should_complete else None
    changed=diff_snapshots(before,snapshot_fields(goal,"development_goal"),"development_goal")
    record_audit_event(child_id=goal.child_id,actor_user_id=user_id,action="update",entity_type="development_goal",entity_id=goal.id,changed_fields=changed,recorded_at=goal.target_date)
    db.session.commit();return jsonify(_serialize(goal,role,user_id))
