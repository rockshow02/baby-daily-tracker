"""
Medication Schedule & Adherence — Phase 1. Lihat
backend/docs/MEDICATION_SCHEDULE.md buat kontrak lengkapnya.

TIDAK ADA proses background di sini SAMA SEKALI — persis
routes/reminder_routes.py, status okurensi (upcoming/due/overdue)
SELALU dihitung ULANG di setiap request lewat
utils/medication_schedule_engine.py (murni Python, nerima `now` dari
`now_wib()` yang dipanggil SEKALI per request di sini).

REUSE: MedicationLog (model YANG SUDAH ADA, `models.py`) dipakai APA
ADANYA buat riwayat obat -- endpoint di sini TIDAK PERNAH bikin sistem
riwayat obat kedua, cuma menambah "administer" sebagai jalur BARU buat
mengisi tabel yang SAMA (lihat _act_on_occurrence di bawah).
"""
from datetime import datetime, time, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import IdempotencyKey, MedicationDoseAction, MedicationLog, MedicationSchedule
from utils.access import can_delete_record, get_accessible_child, resolve_role, WRITE_ROLES
from utils.audit import (
    MEDICATION_DOSE_ADMINISTERED_ENTITY_TYPE, MEDICATION_DOSE_SKIPPED_ENTITY_TYPE,
    diff_snapshots, record_audit_event, snapshot_fields,
)
from utils.auth import get_current_user_id
from utils.idempotency import CONFLICT_MESSAGE, compute_fingerprint, idempotent_create
from utils.medication_schedule_engine import (
    DOSE_UNITS, ScheduleValidationError, adherence_percentage, compute_adherence,
    compute_schedule_occurrences, next_actionable_occurrence_at, occurrence_key_for,
    parse_occurrence_key, validate_date_range, validate_dose, validate_instructions,
    validate_medication_name, validate_times_of_day, valid_occurrence_range,
)
from utils.timezone_utils import now_wib

medication_schedule_bp = Blueprint("medication_schedule", __name__)

NO_WRITE_ROLE_MESSAGE = "Peran Anda hanya bisa melihat data, tidak bisa menambah/mengubah jadwal obat."
NO_EDIT_PERMISSION_MESSAGE = "Anda tidak punya izin untuk mengubah jadwal obat ini."
NO_DELETE_PERMISSION_MESSAGE = "Anda tidak punya izin untuk menghapus jadwal obat ini."
SCHEDULE_NOT_FOUND_MESSAGE = "Jadwal obat tidak ditemukan"
OUT_OF_RANGE_MESSAGE = "Dosis ini di luar jangkauan yang bisa diaksi"

ADHERENCE_PERIODS = {"7d": 7, "30d": 30}


def _require_login_and_child(child_id):
    """(child, error_response_atau_None) -- pola SAMA PERSIS routes/reminder_routes.py."""
    user_id = get_current_user_id()
    if not user_id:
        return None, (jsonify({"error": "Belum login"}), 401)
    child = get_accessible_child(child_id, user_id)
    if not child:
        return None, (jsonify({"error": "Anak tidak ditemukan"}), 404)
    return child, None


def _parse_date_field(raw, field_name, required=True):
    if raw is None:
        if required:
            raise ScheduleValidationError(f"{field_name} wajib diisi (format YYYY-MM-DD)")
        return None
    if not isinstance(raw, str):
        raise ScheduleValidationError(f"{field_name} tidak valid")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise ScheduleValidationError(f"{field_name} tidak valid, format harus YYYY-MM-DD")


def _validate_schedule_payload(data, partial):
    """
    Balikin dict field-yang-sudah-divalidasi (CUMA berisi key yang
    dikirim kalau `partial=True`), atau raise ScheduleValidationError.
    `partial=False` (POST create) -- medication_name/start_date/
    times_of_day WAJIB ada.
    """
    result = {}

    if not partial or "medication_name" in data:
        result["medication_name"] = validate_medication_name(data.get("medication_name"))

    if not partial or "dose_value" in data or "dose_unit" in data:
        result["dose_value"], result["dose_unit"] = validate_dose(data.get("dose_value"), data.get("dose_unit"))

    if not partial or "instructions" in data:
        result["instructions"] = validate_instructions(data.get("instructions"))

    if not partial or "times_of_day" in data:
        result["times_of_day"] = validate_times_of_day(data.get("times_of_day"))

    if not partial or "start_date" in data:
        result["start_date"] = _parse_date_field(data.get("start_date"), "start_date")

    if "end_date" in data or not partial:
        result["end_date"] = _parse_date_field(data.get("end_date"), "end_date", required=False)

    start_for_check = result.get("start_date")
    end_for_check = result.get("end_date") if "end_date" in result else None
    if start_for_check is not None and ("end_date" in result):
        validate_date_range(start_for_check, end_for_check)

    if "is_active" in data:
        if not isinstance(data.get("is_active"), bool):
            raise ScheduleValidationError("is_active harus bernilai boolean")
        result["is_active"] = data["is_active"]

    return result


def _capabilities(role, created_by_user_id, user_id):
    return {
        "can_edit": can_delete_record(role, created_by_user_id, user_id),
        "can_delete": can_delete_record(role, created_by_user_id, user_id),
        "can_act": role in WRITE_ROLES,
    }


def _occurrence_to_json(o, can_act_schedule, occ_range):
    occ_at = o["occurrence_at"]
    date_eligible = occ_range is not None and occ_range[0] <= occ_at <= occ_range[1]
    can_act = bool(can_act_schedule) and date_eligible and o["status"] is None
    return {
        "occurrence_key": o["occurrence_key"],
        "occurrence_at": o["occurrence_at"].isoformat() + "+07:00",
        "state": o["state"],
        "status": o["status"],
        "acted_at": (o["acted_at"].isoformat() + "+07:00") if o["acted_at"] else None,
        "acted_by_user_id": o["acted_by_user_id"],
        "acted_by_name": o["acted_by_name"],
        "medication_log_id": o["medication_log_id"],
        "can_act": can_act,
    }


# --------------------------------------------------------------------------
# GET / POST /children/<child_id>/medication-schedules
# --------------------------------------------------------------------------

@medication_schedule_bp.route("/children/<int:child_id>/medication-schedules", methods=["GET"])
def list_medication_schedules(child_id):
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()
    role = resolve_role(child, user_id)

    now = now_wib()
    today = now.date()

    schedules = (
        MedicationSchedule.query.filter_by(child_id=child_id)
        .order_by(MedicationSchedule.created_at.asc())
        .all()
    )

    schedule_dicts = []
    due_count = 0
    overdue_count = 0
    next_upcoming_candidates = []

    for s in schedules:
        occ_range = valid_occurrence_range(s, today)
        if occ_range is None:
            actions_by_occurrence = {}
        else:
            earliest, latest = occ_range
            actions = MedicationDoseAction.query.filter(
                MedicationDoseAction.schedule_id == s.id,
                MedicationDoseAction.occurrence_at >= earliest,
                MedicationDoseAction.occurrence_at <= latest,
            ).all()
            actions_by_occurrence = {a.occurrence_at: a for a in actions}

        occurrences = compute_schedule_occurrences(s, actions_by_occurrence, today, now)
        next_at = next_actionable_occurrence_at(s, actions_by_occurrence, today, now)

        for occ in occurrences:
            if occ["state"] == "due":
                due_count += 1
            elif occ["state"] == "overdue":
                overdue_count += 1
        if next_at is not None:
            next_upcoming_candidates.append(next_at)

        caps = _capabilities(role, s.created_by_user_id, user_id)
        schedule_dicts.append({
            **s.to_dict(),
            **caps,
            "next_occurrence_at": (next_at.isoformat() + "+07:00") if next_at else None,
            "occurrences": [_occurrence_to_json(o, caps["can_act"], occ_range) for o in occurrences],
        })

    next_upcoming_at = min(next_upcoming_candidates) if next_upcoming_candidates else None

    return jsonify({
        "child_id": child_id,
        "timezone": "Asia/Jakarta",
        "server_time": now.isoformat() + "+07:00",
        "schedules": schedule_dicts,
        "summary": {
            "due_count": due_count,
            "overdue_count": overdue_count,
            "next_upcoming_at": (next_upcoming_at.isoformat() + "+07:00") if next_upcoming_at else None,
        },
        "dose_units": list(DOSE_UNITS),
        "can_create": role in WRITE_ROLES,
    })


@medication_schedule_bp.route("/children/<int:child_id>/medication-schedules", methods=["POST"])
def create_medication_schedule(child_id):
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()
    if resolve_role(child, user_id) not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Format data tidak valid"}), 400

    try:
        fields = _validate_schedule_payload(data, partial=False)
    except ScheduleValidationError as exc:
        return jsonify({"error": exc.message}), 400

    client_request_id = request.headers.get("X-Idempotency-Key")
    fingerprint = compute_fingerprint(data)

    def build():
        schedule = MedicationSchedule(
            child_id=child_id,
            created_by_user_id=user_id,
            medication_name=fields["medication_name"],
            dose_value=fields["dose_value"],
            dose_unit=fields["dose_unit"],
            instructions=fields["instructions"],
            start_date=fields["start_date"],
            end_date=fields.get("end_date"),
            times_of_day=fields["times_of_day"],
            timezone="Asia/Jakarta",
            is_active=True,
        )
        db.session.add(schedule)
        db.session.flush()
        record_audit_event(
            child_id=child_id, actor_user_id=user_id, action="create",
            entity_type="medication_schedule", entity_id=schedule.id,
            recorded_at=datetime.combine(schedule.start_date, time.min),
        )
        return schedule.to_dict()

    body, status, _ = idempotent_create(user_id, child_id, "medication-schedules", client_request_id, fingerprint, build)
    return jsonify(body), status


# --------------------------------------------------------------------------
# PATCH / DELETE /children/<child_id>/medication-schedules/<schedule_id>
# --------------------------------------------------------------------------

@medication_schedule_bp.route("/children/<int:child_id>/medication-schedules/<int:schedule_id>", methods=["PATCH"])
def update_medication_schedule(child_id, schedule_id):
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()

    schedule = MedicationSchedule.query.filter_by(id=schedule_id, child_id=child_id).first()
    if not schedule:
        return jsonify({"error": SCHEDULE_NOT_FOUND_MESSAGE}), 404

    role = resolve_role(child, user_id)
    if not can_delete_record(role, schedule.created_by_user_id, user_id):
        return jsonify({"error": NO_EDIT_PERMISSION_MESSAGE}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Format data tidak valid"}), 400

    try:
        fields = _validate_schedule_payload(data, partial=True)
    except ScheduleValidationError as exc:
        return jsonify({"error": exc.message}), 400

    # Rentang tanggal WAJIB tetap dicek konsisten walau CUMA salah satu
    # dari start_date/end_date yang dikirim kali ini (bandingin ke nilai
    # yang SUDAH tersimpan buat field yang nggak dikirim).
    effective_start = fields.get("start_date", schedule.start_date)
    effective_end = fields["end_date"] if "end_date" in fields else schedule.end_date
    try:
        validate_date_range(effective_start, effective_end)
    except ScheduleValidationError as exc:
        return jsonify({"error": exc.message}), 400

    before = snapshot_fields(schedule, "medication_schedule")
    for field in ("medication_name", "dose_value", "dose_unit", "instructions", "start_date", "times_of_day", "is_active"):
        if field in fields:
            setattr(schedule, field, fields[field])
    if "end_date" in fields:
        schedule.end_date = fields["end_date"]

    changed = diff_snapshots(before, snapshot_fields(schedule, "medication_schedule"), "medication_schedule")
    if changed:
        record_audit_event(
            child_id=child_id, actor_user_id=user_id, action="update",
            entity_type="medication_schedule", entity_id=schedule.id, changed_fields=changed,
            recorded_at=datetime.combine(schedule.start_date, time.min),
        )
    db.session.commit()
    return jsonify(schedule.to_dict())


@medication_schedule_bp.route("/children/<int:child_id>/medication-schedules/<int:schedule_id>", methods=["DELETE"])
def delete_medication_schedule(child_id, schedule_id):
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()

    schedule = MedicationSchedule.query.filter_by(id=schedule_id, child_id=child_id).first()
    if not schedule:
        return jsonify({"error": SCHEDULE_NOT_FOUND_MESSAGE}), 404

    role = resolve_role(child, user_id)
    if not can_delete_record(role, schedule.created_by_user_id, user_id):
        return jsonify({"error": NO_DELETE_PERMISSION_MESSAGE}), 403

    record_audit_event(
        child_id=child_id, actor_user_id=user_id, action="delete",
        entity_type="medication_schedule", entity_id=schedule.id,
        recorded_at=datetime.combine(schedule.start_date, time.min),
    )
    db.session.delete(schedule)
    db.session.commit()
    return jsonify({"success": True})


# --------------------------------------------------------------------------
# POST .../occurrences/<occurrence_key>/administer | /skip
#
# Idempotensi 2 LAPIS -- pola SAMA PERSIS
# routes/reminder_routes.py:_act_on_occurrence:
#   1. client_request_id yang SAMA diulang -> respons ASLI, tidak bikin baris baru.
#   2. Okurensi yang SAMA (schedule_id + occurrence_at) diaksi dari
#      client_request_id yang BEDA -> 409, tidak pernah menimpa.
#
# BEDA dari reminder: status='administered' SELALU membuat 1
# MedicationLog BARU (bukan opsional lewat "Catat sekarang") --
# dibuat DALAM TRANSAKSI YANG SAMA dengan MedicationDoseAction-nya
# (requirement: "never create duplicate medication logs during retries
# or concurrent requests" -- dijamin OLEH mekanisme idempotensi/
# konflik yang SAMA yang melindungi baris aksinya sendiri, karena
# keduanya di-flush/commit BARENG dalam 1 transaksi).
# --------------------------------------------------------------------------

def _act_on_occurrence(child_id, schedule_id, occurrence_key, status, endpoint_name):
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()

    schedule = MedicationSchedule.query.filter_by(id=schedule_id, child_id=child_id).first()
    if not schedule:
        return jsonify({"error": SCHEDULE_NOT_FOUND_MESSAGE}), 404

    role = resolve_role(child, user_id)
    if role not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    if not schedule.is_active:
        return jsonify({"error": "Jadwal obat ini sudah nonaktif"}), 400

    occurrence_at = parse_occurrence_key(occurrence_key)
    if occurrence_at is None:
        return jsonify({"error": "Format occurrence_key tidak valid, harus YYYY-MM-DDTHH:MM"}), 400
    if occurrence_at.strftime("%H:%M") not in (schedule.times_of_day or []):
        return jsonify({"error": OUT_OF_RANGE_MESSAGE}), 400

    today = now_wib().date()
    occ_range = valid_occurrence_range(schedule, today)
    if occ_range is None:
        return jsonify({"error": OUT_OF_RANGE_MESSAGE}), 400
    earliest, latest = occ_range
    if not (earliest <= occurrence_at <= latest):
        return jsonify({"error": OUT_OF_RANGE_MESSAGE}), 400

    client_request_id = request.headers.get("X-Idempotency-Key")
    fingerprint = compute_fingerprint({
        "schedule_id": schedule_id, "occurrence_key": occurrence_key, "status": status,
    })

    def _existing_replay():
        if not client_request_id:
            return None
        existing_key = IdempotencyKey.query.filter_by(
            user_id=user_id, child_id=child_id, endpoint=endpoint_name, client_request_id=client_request_id,
        ).first()
        if not existing_key:
            return None
        if existing_key.fingerprint and existing_key.fingerprint != fingerprint:
            return jsonify(CONFLICT_MESSAGE), 409
        return jsonify(existing_key.response_body), existing_key.response_status

    replay = _existing_replay()
    if replay:
        return replay

    def _occurrence_conflict():
        existing_action = MedicationDoseAction.query.filter_by(
            schedule_id=schedule_id, occurrence_at=occurrence_at,
        ).first()
        if not existing_action:
            return None
        return jsonify({
            "error": "Dosis ini sudah pernah ditandai sebelumnya.",
            "current_status": existing_action.status,
        }), 409

    conflict = _occurrence_conflict()
    if conflict:
        return conflict

    acted_at = now_wib()
    medication_log_id = None

    if status == "administered":
        dosage = f"{schedule.dose_value:g} {schedule.dose_unit}" if schedule.dose_value is not None else None
        log = MedicationLog(
            child_id=child_id,
            medication_name=schedule.medication_name,
            dosage=dosage,
            timestamp=acted_at,
            created_by_user_id=user_id,
        )
        db.session.add(log)
        db.session.flush()
        medication_log_id = log.id
        record_audit_event(
            child_id=child_id, actor_user_id=user_id, action="create",
            entity_type="medication_log", entity_id=log.id, recorded_at=acted_at,
        )

    action = MedicationDoseAction(
        schedule_id=schedule_id,
        occurrence_at=occurrence_at,
        status=status,
        acted_at=acted_at,
        acted_by_user_id=user_id,
        medication_log_id=medication_log_id,
    )
    db.session.add(action)
    db.session.flush()

    entity_type = (
        MEDICATION_DOSE_ADMINISTERED_ENTITY_TYPE if status == "administered"
        else MEDICATION_DOSE_SKIPPED_ENTITY_TYPE
    )
    record_audit_event(
        child_id=child_id, actor_user_id=user_id, action="create",
        entity_type=entity_type, entity_id=action.id, recorded_at=occurrence_at,
    )

    body = action.to_dict()
    if client_request_id:
        db.session.add(IdempotencyKey(
            user_id=user_id, child_id=child_id, endpoint=endpoint_name,
            client_request_id=client_request_id, fingerprint=fingerprint,
            response_status=201, response_body=body,
        ))

    try:
        db.session.commit()
    except IntegrityError:
        # Race genuine (2 request nyampe hampir bersamaan, mis. 2
        # caregiver nge-tap hampir bersamaan) -- SELURUH transaksi
        # (termasuk MedicationLog yang barusan di-flush kalau ada) kena
        # rollback bareng, jadi TIDAK PERNAH ada log obat "yatim" tanpa
        # aksi yang menang, ataupun aksi tanpa log-nya.
        db.session.rollback()
        replay = _existing_replay()
        if replay:
            return replay
        conflict = _occurrence_conflict()
        if conflict:
            return conflict
        raise

    return jsonify(body), 201


@medication_schedule_bp.route(
    "/children/<int:child_id>/medication-schedules/<int:schedule_id>/occurrences/<occurrence_key>/administer",
    methods=["POST"],
)
def administer_occurrence(child_id, schedule_id, occurrence_key):
    return _act_on_occurrence(child_id, schedule_id, occurrence_key, "administered", "medication-schedule-administer")


@medication_schedule_bp.route(
    "/children/<int:child_id>/medication-schedules/<int:schedule_id>/occurrences/<occurrence_key>/skip",
    methods=["POST"],
)
def skip_occurrence(child_id, schedule_id, occurrence_key):
    return _act_on_occurrence(child_id, schedule_id, occurrence_key, "skipped", "medication-schedule-skip")


# --------------------------------------------------------------------------
# GET /children/<child_id>/medication-schedules/adherence?period=7d|30d
# --------------------------------------------------------------------------

@medication_schedule_bp.route("/children/<int:child_id>/medication-schedules/adherence", methods=["GET"])
def medication_adherence(child_id):
    child, err = _require_login_and_child(child_id)
    if err:
        return err

    period_key = request.args.get("period") or "7d"
    if period_key not in ADHERENCE_PERIODS:
        return jsonify({"error": "Periode tidak didukung. Gunakan '7d' atau '30d'."}), 400
    days = ADHERENCE_PERIODS[period_key]

    now = now_wib()
    period_end = now.date()
    period_start = period_end - timedelta(days=days - 1)

    period_start_dt = datetime.combine(period_start, time.min)
    period_end_dt = datetime.combine(period_end, time.max)

    schedules = MedicationSchedule.query.filter(
        MedicationSchedule.child_id == child_id,
        MedicationSchedule.start_date <= period_end,
        db.or_(MedicationSchedule.end_date.is_(None), MedicationSchedule.end_date >= period_start),
    ).all()

    totals = {
        "expected_count": 0, "administered_count": 0, "skipped_count": 0,
        "overdue_unresolved_count": 0, "on_time_administered_count": 0, "late_administered_count": 0,
    }
    for s in schedules:
        actions = MedicationDoseAction.query.filter(
            MedicationDoseAction.schedule_id == s.id,
            MedicationDoseAction.occurrence_at >= period_start_dt,
            MedicationDoseAction.occurrence_at <= period_end_dt,
        ).all()
        actions_by_occurrence = {a.occurrence_at: a for a in actions}
        per_schedule = compute_adherence(s, actions_by_occurrence, period_start, period_end, now)
        for key in totals:
            totals[key] += per_schedule[key]

    return jsonify({
        "child_id": child_id,
        "period": {
            "key": period_key, "days": days,
            "start_date": period_start.isoformat(), "end_date": period_end.isoformat(),
            "timezone": "Asia/Jakarta",
        },
        **totals,
        "adherence_percentage": adherence_percentage(totals["expected_count"], totals["administered_count"]),
    })
