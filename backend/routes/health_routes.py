from datetime import datetime

from flask import Blueprint, request, jsonify, session

from extensions import db
from models import Child, DoctorVisitLog, TemperatureLog, IllnessLog, MedicationLog, User
from utils.telegram import notify_other_caregivers
from utils.access import get_accessible_child
from utils.auth import get_current_user_id
from utils.idempotency import idempotent_create, compute_fingerprint
from utils.timezone_utils import now_wib, today_wib, to_wib_naive
from utils.temperature_calc import classify_temperature
from utils.audit import record_audit_event, snapshot_fields, diff_snapshots

health_bp = Blueprint("health", __name__)


def _owned_child(child_id):
    user_id = get_current_user_id()
    if not user_id:
        return None
    return get_accessible_child(child_id, user_id)


def _parse_date(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").date()


# ---------- KUNJUNGAN DOKTER ----------

@health_bp.route("/children/<int:child_id>/doctor-visits", methods=["GET"])
def list_doctor_visits(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404
    visits = (
        DoctorVisitLog.query.filter_by(child_id=child_id)
        .order_by(DoctorVisitLog.visit_date.desc())
        .all()
    )
    return jsonify([v.to_dict() for v in visits])


@health_bp.route("/children/<int:child_id>/doctor-visits", methods=["POST"])
def create_doctor_visit(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    data = request.get_json() or {}
    if not data.get("visit_date"):
        return jsonify({"error": "visit_date wajib diisi"}), 400

    user_id = get_current_user_id()
    visit = DoctorVisitLog(
        created_by_user_id=user_id,
        child_id=child_id,
        visit_date=_parse_date(data["visit_date"]),
        doctor_name=data.get("doctor_name"),
        clinic_name=data.get("clinic_name"),
        reason=data.get("reason"),
        diagnosis=data.get("diagnosis"),
        next_visit_date=_parse_date(data["next_visit_date"]) if data.get("next_visit_date") else None,
        notes=data.get("notes"),
    )
    db.session.add(visit)
    db.session.flush()
    record_audit_event(
        child_id=child_id, actor_user_id=user_id, action="create",
        entity_type="doctor_visit", entity_id=visit.id, recorded_at=visit.visit_date,
    )
    db.session.commit()
    notify_other_caregivers(child, user_id, f"🩺 {User.query.get(user_id).name} mencatat kunjungan dokter untuk {child.nickname or child.name}.")
    return jsonify(visit.to_dict()), 201


@health_bp.route("/doctor-visits/<int:visit_id>", methods=["PUT", "DELETE"])
def update_or_delete_doctor_visit(visit_id):
    visit = DoctorVisitLog.query.get_or_404(visit_id)
    child = _owned_child(visit.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    user_id = get_current_user_id()

    if request.method == "DELETE":
        record_audit_event(
            child_id=visit.child_id, actor_user_id=user_id, action="delete",
            entity_type="doctor_visit", entity_id=visit.id, recorded_at=visit.visit_date,
        )
        db.session.delete(visit)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
    before = snapshot_fields(visit, "doctor_visit")
    if "visit_date" in data:
        visit.visit_date = _parse_date(data["visit_date"])
    if "doctor_name" in data:
        visit.doctor_name = data["doctor_name"]
    if "clinic_name" in data:
        visit.clinic_name = data["clinic_name"]
    if "reason" in data:
        visit.reason = data["reason"]
    if "diagnosis" in data:
        visit.diagnosis = data["diagnosis"]
    if "next_visit_date" in data:
        visit.next_visit_date = _parse_date(data["next_visit_date"]) if data["next_visit_date"] else None
    if "notes" in data:
        visit.notes = data["notes"]
    changed = diff_snapshots(before, snapshot_fields(visit, "doctor_visit"), "doctor_visit")
    if changed:
        record_audit_event(
            child_id=visit.child_id, actor_user_id=user_id, action="update",
            entity_type="doctor_visit", entity_id=visit.id, changed_fields=changed, recorded_at=visit.visit_date,
        )
    db.session.commit()
    return jsonify(visit.to_dict())


# ---------- SUHU TUBUH ----------

@health_bp.route("/children/<int:child_id>/temperature-logs", methods=["GET"])
def list_temperature_logs(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    logs = (
        TemperatureLog.query.filter_by(child_id=child_id)
        .order_by(TemperatureLog.timestamp.desc())
        .limit(100)
        .all()
    )
    result = []
    for log in logs:
        data = log.to_dict()
        data["status"] = classify_temperature(log.temperature_celsius, log.method)
        result.append(data)
    return jsonify(result)


@health_bp.route("/children/<int:child_id>/temperature-logs", methods=["POST"])
def create_temperature_log(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    data = request.get_json() or {}
    temp = data.get("temperature_celsius")
    if temp is None:
        return jsonify({"error": "temperature_celsius wajib diisi"}), 400
    if not (30 <= float(temp) <= 43):
        return jsonify({"error": "Suhu tidak wajar (30-43°C)"}), 400

    user_id = get_current_user_id()
    log = TemperatureLog(
        created_by_user_id=user_id,
        child_id=child_id,
        timestamp=to_wib_naive(data["timestamp"]) if data.get("timestamp") else now_wib(),
        temperature_celsius=temp,
        method=data.get("method", "ketiak"),
        notes=data.get("notes"),
    )
    db.session.add(log)
    db.session.flush()
    record_audit_event(
        child_id=child_id, actor_user_id=user_id, action="create",
        entity_type="temperature_log", entity_id=log.id, recorded_at=log.timestamp,
    )
    db.session.commit()
    notify_other_caregivers(child, user_id, f"🌡️ {User.query.get(user_id).name} mencatat suhu tubuh untuk {child.nickname or child.name}.")

    result = log.to_dict()
    result["status"] = classify_temperature(log.temperature_celsius, log.method)
    return jsonify(result), 201


@health_bp.route("/temperature-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_temperature_log(log_id):
    log = TemperatureLog.query.get_or_404(log_id)
    child = _owned_child(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    user_id = get_current_user_id()

    if request.method == "DELETE":
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="delete",
            entity_type="temperature_log", entity_id=log.id, recorded_at=log.timestamp,
        )
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
    before = snapshot_fields(log, "temperature_log")
    if "timestamp" in data:
        log.timestamp = to_wib_naive(data["timestamp"])
    if "temperature_celsius" in data:
        temp = data["temperature_celsius"]
        if not (30 <= float(temp) <= 43):
            return jsonify({"error": "Suhu tidak wajar (30-43°C)"}), 400
        log.temperature_celsius = temp
    if "method" in data:
        log.method = data["method"]
    if "notes" in data:
        log.notes = data["notes"]
    changed = diff_snapshots(before, snapshot_fields(log, "temperature_log"), "temperature_log")
    if changed:
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="update",
            entity_type="temperature_log", entity_id=log.id, changed_fields=changed, recorded_at=log.timestamp,
        )
    db.session.commit()

    result = log.to_dict()
    result["status"] = classify_temperature(log.temperature_celsius, log.method)
    return jsonify(result)


# ---------- SAKIT / PENYAKIT ----------

@health_bp.route("/children/<int:child_id>/illness-logs", methods=["GET"])
def list_illness_logs(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404
    logs = (
        IllnessLog.query.filter_by(child_id=child_id)
        .order_by(IllnessLog.start_date.desc())
        .all()
    )
    result = []
    for log in logs:
        data = log.to_dict()
        data["medications"] = [m.to_dict() for m in log.medications]
        result.append(data)
    return jsonify(result)


@health_bp.route("/children/<int:child_id>/illness-logs", methods=["POST"])
def create_illness_log(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    data = request.get_json() or {}
    if not data.get("illness_name") or not data.get("start_date"):
        return jsonify({"error": "illness_name dan start_date wajib diisi"}), 400

    user_id = get_current_user_id()
    log = IllnessLog(
        created_by_user_id=user_id,
        child_id=child_id,
        illness_name=data["illness_name"],
        start_date=_parse_date(data["start_date"]),
        end_date=_parse_date(data["end_date"]) if data.get("end_date") else None,
        symptoms=data.get("symptoms"),
        notes=data.get("notes"),
    )
    db.session.add(log)
    db.session.flush()
    record_audit_event(
        child_id=child_id, actor_user_id=user_id, action="create",
        entity_type="illness_log", entity_id=log.id, recorded_at=log.start_date,
    )
    db.session.commit()
    notify_other_caregivers(child, user_id, f"🤒 {User.query.get(user_id).name} mencatat sakit untuk {child.nickname or child.name}.")
    return jsonify(log.to_dict()), 201


@health_bp.route("/illness-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_illness_log(log_id):
    log = IllnessLog.query.get_or_404(log_id)
    child = _owned_child(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    user_id = get_current_user_id()

    if request.method == "DELETE":
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="delete",
            entity_type="illness_log", entity_id=log.id, recorded_at=log.start_date,
        )
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
    before = snapshot_fields(log, "illness_log")
    if "illness_name" in data:
        log.illness_name = data["illness_name"]
    if "start_date" in data:
        log.start_date = _parse_date(data["start_date"])
    if "end_date" in data:
        # dipakai buat tandai "sudah sembuh"
        log.end_date = _parse_date(data["end_date"]) if data["end_date"] else None
    if "symptoms" in data:
        log.symptoms = data["symptoms"]
    if "notes" in data:
        log.notes = data["notes"]
    changed = diff_snapshots(before, snapshot_fields(log, "illness_log"), "illness_log")
    if changed:
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="update",
            entity_type="illness_log", entity_id=log.id, changed_fields=changed, recorded_at=log.start_date,
        )
    db.session.commit()
    return jsonify(log.to_dict())


# ---------- OBAT ----------

@health_bp.route("/children/<int:child_id>/medication-logs", methods=["GET"])
def list_medication_logs(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    query = MedicationLog.query.filter_by(child_id=child_id)
    date_str = request.args.get("date")
    if date_str:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        query = query.filter(db.func.date(MedicationLog.timestamp) == target_date)

    logs = query.order_by(MedicationLog.timestamp.desc()).limit(100).all()
    return jsonify([m.to_dict() for m in logs])


@health_bp.route("/children/<int:child_id>/medication-logs", methods=["POST"])
def create_medication_log(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    data = request.get_json() or {}
    if not data.get("medication_name"):
        return jsonify({"error": "medication_name wajib diisi"}), 400

    illness_id = data.get("illness_id")
    if illness_id:
        illness = IllnessLog.query.filter_by(id=illness_id, child_id=child_id).first()
        if not illness:
            return jsonify({"error": "illness_id tidak valid"}), 400

    user_id = get_current_user_id()
    client_request_id = request.headers.get("X-Idempotency-Key")
    fingerprint = compute_fingerprint(data)

    def build():
        log = MedicationLog(
            created_by_user_id=user_id,
            child_id=child_id,
            illness_id=illness_id,
            medication_name=data["medication_name"],
            dosage=data.get("dosage"),
            timestamp=to_wib_naive(data["timestamp"]) if data.get("timestamp") else now_wib(),
            notes=data.get("notes"),
        )
        db.session.add(log)
        db.session.flush()
        record_audit_event(
            child_id=child_id, actor_user_id=user_id, action="create",
            entity_type="medication_log", entity_id=log.id, recorded_at=log.timestamp,
        )
        return log.to_dict()

    def send_notification():
        notify_other_caregivers(child, user_id, f"💊 {User.query.get(user_id).name} mencatat pemberian obat untuk {child.nickname or child.name}.")

    body, status, _ = idempotent_create(
        user_id, child_id, "medication-logs", client_request_id, fingerprint, build, after_commit=send_notification
    )
    return jsonify(body), status


@health_bp.route("/medication-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_medication_log(log_id):
    log = MedicationLog.query.get_or_404(log_id)
    child = _owned_child(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    user_id = get_current_user_id()

    if request.method == "DELETE":
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="delete",
            entity_type="medication_log", entity_id=log.id, recorded_at=log.timestamp,
        )
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
    before = snapshot_fields(log, "medication_log")
    if "timestamp" in data:
        log.timestamp = to_wib_naive(data["timestamp"])
    if "medication_name" in data:
        log.medication_name = data["medication_name"]
    if "dosage" in data:
        log.dosage = data["dosage"]
    if "notes" in data:
        log.notes = data["notes"]
    changed = diff_snapshots(before, snapshot_fields(log, "medication_log"), "medication_log")
    if changed:
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="update",
            entity_type="medication_log", entity_id=log.id, changed_fields=changed, recorded_at=log.timestamp,
        )
    db.session.commit()
    return jsonify(log.to_dict())