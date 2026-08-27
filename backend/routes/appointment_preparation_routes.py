"""Checklist privat persiapan kunjungan dokter."""
from datetime import date

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import AppointmentPreparation, DoctorVisitLog, FamilyDevelopmentCheckIn
from utils.access import WRITE_ROLES, can_delete_record, get_accessible_child, resolve_role
from utils.audit import diff_snapshots, record_audit_event, snapshot_fields
from utils.auth import get_current_user_id

appointment_preparation_bp = Blueprint("appointment_preparation", __name__)
CHECKLIST_KEYS = ("health_book", "identity_or_insurance", "medication_list",
                  "test_results", "child_supplies")


def _context(child_id):
    user_id=get_current_user_id();child=get_accessible_child(child_id,user_id) if user_id else None
    return user_id,child


def _values(data, child_id):
    try: appointment_date=date.fromisoformat(data.get("appointment_date") or "")
    except (TypeError,ValueError): raise ValueError("Tanggal konsultasi tidak valid")
    raw=data.get("checklist")
    if not isinstance(raw,dict) or set(raw)-set(CHECKLIST_KEYS):raise ValueError("Checklist tidak valid")
    checklist={key:raw.get(key,False) for key in CHECKLIST_KEYS}
    if any(not isinstance(value,bool) for value in checklist.values()):raise ValueError("Nilai checklist harus ya atau tidak")
    questions=data.get("questions",[])
    if not isinstance(questions,list) or len(questions)>10:raise ValueError("Pertanyaan maksimal 10 item")
    normalized=[]
    for question in questions:
        if not isinstance(question,str):raise ValueError("Pertanyaan harus berupa teks")
        value=question.replace("\r\n","\n").replace("\r","\n").strip()
        if not value or len(value)>300:raise ValueError("Setiap pertanyaan wajib diisi dan maksimal 300 karakter")
        normalized.append(value)
    if len(set(normalized))!=len(normalized):raise ValueError("Pertanyaan tidak boleh duplikat")
    visit_id=data.get("doctor_visit_id")
    if visit_id is not None:
        if isinstance(visit_id,bool) or not isinstance(visit_id,int):raise ValueError("Kunjungan dokter tidak valid")
        if not DoctorVisitLog.query.filter_by(id=visit_id,child_id=child_id).first():raise ValueError("Kunjungan dokter tidak ditemukan")
    source_ids=data.get("source_check_in_ids",[])
    if not isinstance(source_ids,list) or len(source_ids)>20 or any(isinstance(x,bool) or not isinstance(x,int) for x in source_ids):raise ValueError("Sumber check-in tidak valid")
    source_ids=list(dict.fromkeys(source_ids))
    if source_ids:
        valid={row.id for row in FamilyDevelopmentCheckIn.query.filter(
            FamilyDevelopmentCheckIn.child_id==child_id,FamilyDevelopmentCheckIn.id.in_(source_ids),
            FamilyDevelopmentCheckIn.discuss_with_professional.is_(True)).all()}
        if valid!=set(source_ids):raise ValueError("Sumber check-in tidak ditemukan atau tidak ditandai untuk konsultasi")
    return {"appointment_date":appointment_date,"checklist":checklist,"questions":normalized,
            "doctor_visit_id":visit_id,"source_check_in_ids":source_ids}


def _serialize(row,role,user_id):
    value=row.to_dict();value["can_edit"]=can_delete_record(role,row.created_by_user_id,user_id);value["can_delete"]=value["can_edit"];return value


@appointment_preparation_bp.route("/children/<int:child_id>/appointment-preparations",methods=["GET","POST"])
def collection(child_id):
    user_id,child=_context(child_id)
    if not child:return jsonify({"error":"Anak tidak ditemukan"}),404
    role=resolve_role(child,user_id)
    if request.method=="GET":
        rows=AppointmentPreparation.query.filter_by(child_id=child_id).order_by(AppointmentPreparation.appointment_date.desc(),AppointmentPreparation.id.desc()).limit(100).all()
        visits=DoctorVisitLog.query.filter_by(child_id=child_id).filter(DoctorVisitLog.next_visit_date.isnot(None)).order_by(DoctorVisitLog.next_visit_date.desc()).limit(100).all()
        check_ins=FamilyDevelopmentCheckIn.query.filter_by(child_id=child_id,discuss_with_professional=True).order_by(FamilyDevelopmentCheckIn.period_month.desc()).limit(20).all()
        return jsonify({"items":[_serialize(row,role,user_id) for row in rows],"can_create":role in WRITE_ROLES,
            "visits":[{"id":row.id,"date":row.next_visit_date.isoformat()} for row in visits],
            "suggested_check_ins":[{"id":row.id,"period_month":row.period_month.strftime("%Y-%m"),"created_by_name":row.creator.name if row.creator else None,"reflection_note":row.reflection_note} for row in check_ins],
            "privacy_note":"Pertanyaan dan refleksi hanya terlihat oleh caregiver yang memiliki akses."})
    if role not in WRITE_ROLES:return jsonify({"error":"Peran Anda hanya bisa melihat persiapan konsultasi"}),403
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify({"error":"Format data tidak valid"}),400
    try:values=_values(data,child_id)
    except ValueError as exc:return jsonify({"error":str(exc)}),400
    if AppointmentPreparation.query.filter_by(child_id=child_id,created_by_user_id=user_id,appointment_date=values["appointment_date"]).first():return jsonify({"error":"Anda sudah membuat persiapan untuk tanggal ini"}),409
    row=AppointmentPreparation(child_id=child_id,created_by_user_id=user_id,**values)
    try:
        db.session.add(row);db.session.flush();record_audit_event(child_id=child_id,actor_user_id=user_id,action="create",entity_type="appointment_preparation",entity_id=row.id,recorded_at=row.appointment_date);db.session.commit()
    except IntegrityError:
        db.session.rollback();return jsonify({"error":"Anda sudah membuat persiapan untuk tanggal ini"}),409
    return jsonify(_serialize(row,role,user_id)),201


@appointment_preparation_bp.route("/appointment-preparations/<int:item_id>",methods=["PUT","DELETE"])
def item(item_id):
    row=db.session.get(AppointmentPreparation,item_id)
    if not row:return jsonify({"error":"Persiapan konsultasi tidak ditemukan"}),404
    user_id,child=_context(row.child_id)
    if not child:return jsonify({"error":"Tidak diizinkan"}),403
    role=resolve_role(child,user_id)
    if not can_delete_record(role,row.created_by_user_id,user_id):return jsonify({"error":"Anda tidak punya izin mengubah persiapan ini"}),403
    if request.method=="DELETE":
        record_audit_event(child_id=row.child_id,actor_user_id=user_id,action="delete",entity_type="appointment_preparation",entity_id=row.id,recorded_at=row.appointment_date);db.session.delete(row);db.session.commit();return jsonify({"success":True})
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify({"error":"Format data tidak valid"}),400
    before=snapshot_fields(row,"appointment_preparation")
    try:values=_values(data,row.child_id)
    except ValueError as exc:return jsonify({"error":str(exc)}),400
    duplicate=AppointmentPreparation.query.filter(AppointmentPreparation.child_id==row.child_id,AppointmentPreparation.created_by_user_id==row.created_by_user_id,AppointmentPreparation.appointment_date==values["appointment_date"],AppointmentPreparation.id!=row.id).first()
    if duplicate:return jsonify({"error":"Anda sudah membuat persiapan untuk tanggal ini"}),409
    for key,value in values.items():setattr(row,key,value)
    changed=diff_snapshots(before,snapshot_fields(row,"appointment_preparation"),"appointment_preparation")
    if changed:
        record_audit_event(child_id=row.child_id,actor_user_id=user_id,action="update",entity_type="appointment_preparation",entity_id=row.id,changed_fields=changed,recorded_at=row.appointment_date)
        try:db.session.commit()
        except IntegrityError:db.session.rollback();return jsonify({"error":"Anda sudah membuat persiapan untuk tanggal ini"}),409
    return jsonify(_serialize(row,role,user_id))
