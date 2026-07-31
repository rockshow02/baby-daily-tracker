import base64
import os
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, session, request, current_app

from extensions import db
from models import (
    Child, FeedingLog, SleepLog, DiaperLog, PumpingLog, ActivityLog,
    MedicationLog, TemperatureLog, DoctorVisitLog, IllnessLog,
    GrowthMeasurement, ChildVaccination, VaccineSchedule, MoodLog, MilestoneLog,
    ChildCaregiver,
)
from utils.access import get_accessible_child

backup_bp = Blueprint("backup", __name__)

EXPORT_VERSION = 1


def _owned_child(child_id):
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_accessible_child(child_id, user_id)


def _iso(d):
    return d.isoformat() if d else None


def _uploads_dir():
    return os.path.join(current_app.root_path, "uploads")


@backup_bp.route("/children/<int:child_id>/export-json", methods=["GET"])
def export_json(child_id):
    """
    Backup lengkap semua data anak dalam format JSON, buat dipulihkan
    di device lain lewat endpoint /children/import-json.
    """
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    photo_base64 = None
    photo_ext = None
    if child.photo_filename:
        path = os.path.join(_uploads_dir(), child.photo_filename)
        if os.path.exists(path):
            with open(path, "rb") as f:
                photo_base64 = base64.b64encode(f.read()).decode("ascii")
            photo_ext = child.photo_filename.rsplit(".", 1)[-1]

    illnesses = IllnessLog.query.filter_by(child_id=child_id).order_by(IllnessLog.id.asc()).all()
    illness_local_id = {ill.id: idx for idx, ill in enumerate(illnesses)}

    vaccinations = ChildVaccination.query.filter_by(child_id=child_id).all()

    data = {
        "export_version": EXPORT_VERSION,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "child": {
            "name": child.name,
            "birth_date": _iso(child.birth_date),
            "gender": child.gender,
            "birth_weight_kg": child.birth_weight_kg,
            "birth_height_cm": child.birth_height_cm,
            "photo_base64": photo_base64,
            "photo_ext": photo_ext,
        },
        "feeding_logs": [
            {
                "timestamp": l.timestamp.isoformat(),
                "feed_type": l.feed_type,
                "duration_minutes": l.duration_minutes,
                "volume_ml": l.volume_ml,
                "breast_side": l.breast_side,
                "notes": l.notes,
            }
            for l in FeedingLog.query.filter_by(child_id=child_id).all()
        ],
        "sleep_logs": [
            {
                "start_time": l.start_time.isoformat(),
                "end_time": l.end_time.isoformat() if l.end_time else None,
                "sleep_type": l.sleep_type,
                "notes": l.notes,
            }
            for l in SleepLog.query.filter_by(child_id=child_id).all()
        ],
        "diaper_logs": [
            {
                "timestamp": l.timestamp.isoformat(),
                "diaper_type": l.diaper_type,
                "consistency": l.consistency,
                "color": l.color,
                "notes": l.notes,
            }
            for l in DiaperLog.query.filter_by(child_id=child_id).all()
        ],
        "pumping_logs": [
            {
                "timestamp": l.timestamp.isoformat(),
                "duration_minutes": l.duration_minutes,
                "volume_ml": l.volume_ml,
                "breast_side": l.breast_side,
                "notes": l.notes,
            }
            for l in PumpingLog.query.filter_by(child_id=child_id).all()
        ],
        "activity_logs": [
            {
                "timestamp": l.timestamp.isoformat(),
                "activity_type": l.activity_type,
                "duration_minutes": l.duration_minutes,
                "notes": l.notes,
            }
            for l in ActivityLog.query.filter_by(child_id=child_id).all()
        ],
        "medication_logs": [
            {
                "timestamp": l.timestamp.isoformat(),
                "medication_name": l.medication_name,
                "dosage": l.dosage,
                "notes": l.notes,
                "illness_local_id": illness_local_id.get(l.illness_id),
            }
            for l in MedicationLog.query.filter_by(child_id=child_id).all()
        ],
        "temperature_logs": [
            {
                "timestamp": l.timestamp.isoformat(),
                "temperature_celsius": l.temperature_celsius,
                "method": l.method,
                "notes": l.notes,
            }
            for l in TemperatureLog.query.filter_by(child_id=child_id).all()
        ],
        "doctor_visits": [
            {
                "visit_date": _iso(v.visit_date),
                "doctor_name": v.doctor_name,
                "clinic_name": v.clinic_name,
                "reason": v.reason,
                "diagnosis": v.diagnosis,
                "next_visit_date": _iso(v.next_visit_date),
                "notes": v.notes,
            }
            for v in DoctorVisitLog.query.filter_by(child_id=child_id).all()
        ],
        "illness_logs": [
            {
                "illness_name": ill.illness_name,
                "start_date": _iso(ill.start_date),
                "end_date": _iso(ill.end_date),
                "symptoms": ill.symptoms,
                "notes": ill.notes,
            }
            for ill in illnesses
        ],
        "growth_measurements": [
            {
                "measured_date": _iso(g.measured_date),
                "weight_kg": g.weight_kg,
                "height_cm": g.height_cm,
                "head_circumference_cm": g.head_circumference_cm,
                "notes": g.notes,
            }
            for g in GrowthMeasurement.query.filter_by(child_id=child_id).all()
        ],
        "vaccinations": [
            {
                "vaccine_name": cv.vaccine.vaccine_name,
                "given": cv.given,
                "given_date": _iso(cv.given_date),
            }
            for cv in vaccinations
        ],
        "mood_logs": [
            {"timestamp": l.timestamp.isoformat(), "mood": l.mood, "notes": l.notes}
            for l in MoodLog.query.filter_by(child_id=child_id).all()
        ],
        "milestone_logs": [
            {
                "milestone_type": l.milestone_type,
                "custom_label": l.custom_label,
                "achieved_date": _iso(l.achieved_date),
                "notes": l.notes,
            }
            for l in MilestoneLog.query.filter_by(child_id=child_id).all()
        ],
    }

    return jsonify(data)


@backup_bp.route("/children/import-json", methods=["POST"])
def import_json():
    """
    Pulihkan backup JSON dari export-json jadi anak baru di akun yang
    sedang login. Selalu bikin anak BARU (tidak menimpa anak yang sudah ada),
    biar aman kalau backup-nya diimport lebih dari sekali.
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    data = request.get_json()
    if not data or "child" not in data:
        return jsonify({"error": "Format file backup tidak valid"}), 400

    c = data["child"]
    if not c.get("name") or not c.get("birth_date"):
        return jsonify({"error": "Data anak di file backup tidak lengkap"}), 400

    child = Child(
        user_id=user_id,
        name=c["name"],
        birth_date=datetime.strptime(c["birth_date"], "%Y-%m-%d").date(),
        gender=c.get("gender"),
        birth_weight_kg=c.get("birth_weight_kg"),
        birth_height_cm=c.get("birth_height_cm"),
    )
    db.session.add(child)
    db.session.flush()  # biar dapet child.id sebelum commit
    db.session.add(ChildCaregiver(child_id=child.id, user_id=user_id, role="owner"))

    if c.get("photo_base64"):
        try:
            os.makedirs(_uploads_dir(), exist_ok=True)
            filename = f"child{child.id}_{uuid.uuid4().hex[:8]}.{c.get('photo_ext', 'jpg')}"
            with open(os.path.join(_uploads_dir(), filename), "wb") as f:
                f.write(base64.b64decode(c["photo_base64"]))
            child.photo_filename = filename
        except Exception:
            pass  # foto gagal dipulihkan bukan alasan buat gagalin seluruh import

    for l in data.get("feeding_logs", []):
        db.session.add(FeedingLog(
            child_id=child.id,
            timestamp=datetime.fromisoformat(l["timestamp"]),
            feed_type=l["feed_type"], duration_minutes=l.get("duration_minutes"),
            volume_ml=l.get("volume_ml"), breast_side=l.get("breast_side"), notes=l.get("notes"),
        ))

    for l in data.get("sleep_logs", []):
        db.session.add(SleepLog(
            child_id=child.id,
            start_time=datetime.fromisoformat(l["start_time"]),
            end_time=datetime.fromisoformat(l["end_time"]) if l.get("end_time") else None,
            sleep_type=l.get("sleep_type", "siang"), notes=l.get("notes"),
        ))

    for l in data.get("diaper_logs", []):
        db.session.add(DiaperLog(
            child_id=child.id, timestamp=datetime.fromisoformat(l["timestamp"]),
            diaper_type=l["diaper_type"], consistency=l.get("consistency"),
            color=l.get("color"), notes=l.get("notes"),
        ))

    for l in data.get("pumping_logs", []):
        db.session.add(PumpingLog(
            child_id=child.id, timestamp=datetime.fromisoformat(l["timestamp"]),
            duration_minutes=l.get("duration_minutes"), volume_ml=l.get("volume_ml"),
            breast_side=l.get("breast_side"), notes=l.get("notes"),
        ))

    for l in data.get("activity_logs", []):
        db.session.add(ActivityLog(
            child_id=child.id, timestamp=datetime.fromisoformat(l["timestamp"]),
            activity_type=l["activity_type"], duration_minutes=l.get("duration_minutes"),
            notes=l.get("notes"),
        ))

    for l in data.get("temperature_logs", []):
        db.session.add(TemperatureLog(
            child_id=child.id, timestamp=datetime.fromisoformat(l["timestamp"]),
            temperature_celsius=l["temperature_celsius"], method=l.get("method", "ketiak"),
            notes=l.get("notes"),
        ))

    for v in data.get("doctor_visits", []):
        db.session.add(DoctorVisitLog(
            child_id=child.id, visit_date=datetime.strptime(v["visit_date"], "%Y-%m-%d").date(),
            doctor_name=v.get("doctor_name"), clinic_name=v.get("clinic_name"),
            reason=v.get("reason"), diagnosis=v.get("diagnosis"),
            next_visit_date=datetime.strptime(v["next_visit_date"], "%Y-%m-%d").date() if v.get("next_visit_date") else None,
            notes=v.get("notes"),
        ))

    illness_objs = {}
    for idx, ill in enumerate(data.get("illness_logs", [])):
        obj = IllnessLog(
            child_id=child.id, illness_name=ill["illness_name"],
            start_date=datetime.strptime(ill["start_date"], "%Y-%m-%d").date(),
            end_date=datetime.strptime(ill["end_date"], "%Y-%m-%d").date() if ill.get("end_date") else None,
            symptoms=ill.get("symptoms"), notes=ill.get("notes"),
        )
        db.session.add(obj)
        illness_objs[idx] = obj
    db.session.flush()  # biar obj.id keisi

    for l in data.get("medication_logs", []):
        illness_id = None
        local_id = l.get("illness_local_id")
        if local_id is not None and local_id in illness_objs:
            illness_id = illness_objs[local_id].id
        db.session.add(MedicationLog(
            child_id=child.id, illness_id=illness_id,
            timestamp=datetime.fromisoformat(l["timestamp"]),
            medication_name=l["medication_name"], dosage=l.get("dosage"), notes=l.get("notes"),
        ))

    for g in data.get("growth_measurements", []):
        db.session.add(GrowthMeasurement(
            child_id=child.id, measured_date=datetime.strptime(g["measured_date"], "%Y-%m-%d").date(),
            weight_kg=g.get("weight_kg"), height_cm=g.get("height_cm"),
            head_circumference_cm=g.get("head_circumference_cm"), notes=g.get("notes"),
        ))

    vaccine_by_name = {v.vaccine_name: v for v in VaccineSchedule.query.all()}
    for v in data.get("vaccinations", []):
        schedule = vaccine_by_name.get(v["vaccine_name"])
        if not schedule:
            continue
        db.session.add(ChildVaccination(
            child_id=child.id, vaccine_schedule_id=schedule.id,
            given=v.get("given", False),
            given_date=datetime.strptime(v["given_date"], "%Y-%m-%d").date() if v.get("given_date") else None,
        ))

    for l in data.get("mood_logs", []):
        db.session.add(MoodLog(
            child_id=child.id, timestamp=datetime.fromisoformat(l["timestamp"]),
            mood=l["mood"], notes=l.get("notes"),
        ))

    for l in data.get("milestone_logs", []):
        db.session.add(MilestoneLog(
            child_id=child.id, milestone_type=l["milestone_type"],
            custom_label=l.get("custom_label"),
            achieved_date=datetime.strptime(l["achieved_date"], "%Y-%m-%d").date(),
            notes=l.get("notes"),
        ))

    db.session.commit()

    return jsonify({"success": True, "child": child.to_dict()}), 201