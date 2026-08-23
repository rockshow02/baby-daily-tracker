"""
Care Reminders & Schedules — Phase 1. Lihat backend/docs/REMINDERS.md
buat kontrak lengkapnya.

TIDAK ADA proses background di sini SAMA SEKALI — status okurensi
(upcoming/due/overdue) SELALU dihitung ULANG di setiap request lewat
utils/reminder_engine.py (murni Python, nerima `now` dari
`now_wib()` yang dipanggil SEKALI per request di sini), TIDAK PERNAH
dipercaya dari klien.
"""
from datetime import datetime, time

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import (
    DoctorVisitLog, IdempotencyKey, MedicationLog, PumpingLog,
    Reminder, ReminderAction,
)
from utils.access import can_delete_record, get_accessible_child, resolve_role, WRITE_ROLES
from utils.audit import (
    REMINDER_OCCURRENCE_COMPLETED_ENTITY_TYPE, REMINDER_OCCURRENCE_SKIPPED_ENTITY_TYPE,
    diff_snapshots, record_audit_event, snapshot_fields,
)
from utils.auth import get_current_user_id
from utils.idempotency import CONFLICT_MESSAGE, compute_fingerprint, idempotent_create
from utils.reminder_engine import (
    LINKABLE_LOG_TYPES, RECURRENCE_VALUES, REMINDER_TYPES,
    compute_reminder_occurrences, next_pending_occurrence_at,
    occurrence_datetime_for_date, parse_occurrence_key, valid_occurrence_date_range,
)
from utils.timezone_utils import now_wib, to_wib_naive

reminder_bp = Blueprint("reminder", __name__)

MAX_TITLE_LENGTH = 150

NO_WRITE_ROLE_MESSAGE = "Peran Anda hanya bisa melihat data, tidak bisa menambah/mengubah pengingat."
NO_EDIT_PERMISSION_MESSAGE = "Anda tidak punya izin untuk mengubah pengingat ini."
NO_DELETE_PERMISSION_MESSAGE = "Anda tidak punya izin untuk menghapus pengingat ini."
REMINDER_NOT_FOUND_MESSAGE = "Pengingat tidak ditemukan"

_LINKABLE_MODELS = {
    "medication_log": MedicationLog,
    "pumping_log": PumpingLog,
    "doctor_visit": DoctorVisitLog,
}


def _require_login_and_child(child_id):
    """
    (child, error_response_atau_None) -- SATU tempat buat pola otorisasi
    yang SAMA di semua endpoint reminder: 401 kalau belum login sama
    sekali (beda dari "anak nggak ketemu"), 404 generik buat anak yang
    beneran nggak ada ATAUPUN nggak bisa diakses user ini (2 kasus itu
    SENGAJA nggak dibedain di respons — user yang nggak berwenang nggak
    boleh bisa nebak "anak ini ada tapi kamu ditolak" vs "anak ini nggak
    ada"). Pola ini SAMA PERSIS kayak routes/insights_routes.py.
    """
    user_id = get_current_user_id()
    if not user_id:
        return None, (jsonify({"error": "Belum login"}), 401)
    child = get_accessible_child(child_id, user_id)
    if not child:
        return None, (jsonify({"error": "Anak tidak ditemukan"}), 404)
    return child, None


def _validate_reminder_payload(data, partial):
    """
    `partial=False` (POST create) -- `reminder_type`/`title`/`scheduled_at`
    WAJIB ada. `partial=True` (PATCH update) -- field yang nggak dikirim
    dilewatin apa adanya (nggak diubah), field yang DIKIRIM tetap divalidasi
    penuh. Balikin pesan error (string) kalau ada masalah, None kalau valid.
    """
    if not partial or "reminder_type" in data:
        if data.get("reminder_type") not in REMINDER_TYPES:
            return f"reminder_type harus salah satu dari: {', '.join(REMINDER_TYPES)}"

    if not partial or "title" in data:
        title = data.get("title")
        if not isinstance(title, str) or not (1 <= len(title.strip()) <= MAX_TITLE_LENGTH):
            return f"title wajib diisi (1-{MAX_TITLE_LENGTH} karakter)"

    if not partial or "scheduled_at" in data:
        raw = data.get("scheduled_at")
        if not raw or not isinstance(raw, str):
            return "scheduled_at wajib diisi"
        try:
            to_wib_naive(raw)
        except (ValueError, TypeError):
            return "Format scheduled_at tidak valid"

    if "recurrence" in data and data.get("recurrence") not in RECURRENCE_VALUES:
        return f"recurrence harus salah satu dari: {', '.join(RECURRENCE_VALUES)}"

    if "is_active" in data and not isinstance(data.get("is_active"), bool):
        return "is_active harus bernilai boolean"

    return None


def _log_belongs_to_child(linked_log_type, linked_log_id, child_id):
    """
    False kalau `linked_log_type` di luar allowlist, ATAUPUN kalau
    log-nya nggak ketemu/bukan milik `child_id` ini — dua-duanya sama-
    sama ditolak, biar reminder anak A nggak pernah bisa ditautkan ke
    catatan anak B (IDOR).
    """
    model = _LINKABLE_MODELS.get(linked_log_type)
    if not model:
        return False
    return db.session.query(model.id).filter_by(id=linked_log_id, child_id=child_id).first() is not None


def _occurrence_to_json(o, reminder_can_act, date_range):
    """
    `can_act`: OTORITATIF dari backend (bukan cuma role, TAPI JUGA
    tanggal okurensi INI dicek terhadap `date_range` --
    `valid_occurrence_date_range()` yang SAMA PERSIS dipakai
    `_act_on_occurrence` buat validasi beneran, jadi frontend nggak
    perlu -- dan nggak boleh -- ngitung ulang eligibility tanggal
    sendiri pakai timezone browser. `date_range` `None` berarti TIDAK
    ADA okurensi reminder ini yang bisa diaksi sama sekali sekarang.
    """
    occ_date = o["occurrence_at"].date()
    date_eligible = date_range is not None and date_range[0] <= occ_date <= date_range[1]
    can_act = bool(reminder_can_act) and date_eligible and o["status"] is None
    return {
        "occurrence_key": o["occurrence_key"],
        "occurrence_at": o["occurrence_at"].isoformat() + "+07:00",
        "state": o["state"],
        "status": o["status"],
        "acted_at": (o["acted_at"].isoformat() + "+07:00") if o["acted_at"] else None,
        "acted_by_user_id": o["acted_by_user_id"],
        "acted_by_name": o["acted_by_name"],
        "linked_log_type": o["linked_log_type"],
        "linked_log_id": o["linked_log_id"],
        "can_act": can_act,
    }


# --------------------------------------------------------------------------
# GET / POST /children/<child_id>/reminders
# --------------------------------------------------------------------------

@reminder_bp.route("/children/<int:child_id>/reminders", methods=["GET"])
def list_reminders(child_id):
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()
    role = resolve_role(child, user_id)

    now = now_wib()
    today = now.date()

    reminders = Reminder.query.filter_by(child_id=child_id).order_by(Reminder.scheduled_at.asc()).all()

    reminder_dicts = []
    due_count = 0
    overdue_count = 0
    next_upcoming_candidates = []

    for r in reminders:
        # Query dibatasi ke rentang lookback yang RELEVAN doang buat
        # reminder INI (bukan seluruh riwayat) -- lihat
        # utils/reminder_engine.py:valid_occurrence_date_range(). `None`
        # (reminder 'none' yang jadwalnya, ATAU reminder 'daily' yang
        # tanggal mulainya, masih di masa depan) berarti TIDAK ADA
        # okurensi/aksi yang mungkin ada buat reminder ini SAMA SEKALI
        # sekarang (compute_reminder_occurrences/next_pending_occurrence_at
        # dua-duanya nggak pernah konsultasi actions_by_date buat reminder
        # yang belum mulai) -- lewati query ReminderAction sama sekali,
        # bukan cuma "asal jangan crash".
        date_range = valid_occurrence_date_range(r.scheduled_at, r.recurrence, today)
        if date_range is None:
            actions_by_date = {}
        else:
            earliest, _latest = date_range
            lookback_start_dt = datetime.combine(earliest, time.min)
            actions = ReminderAction.query.filter(
                ReminderAction.reminder_id == r.id,
                ReminderAction.occurrence_at >= lookback_start_dt,
            ).all()
            actions_by_date = {a.occurrence_at.date(): a for a in actions}

        occurrences = compute_reminder_occurrences(r, actions_by_date, today, now)
        next_at = next_pending_occurrence_at(r, actions_by_date, today)

        for occ in occurrences:
            if occ["state"] == "due":
                due_count += 1
            elif occ["state"] == "overdue":
                overdue_count += 1
        if next_at is not None:
            next_upcoming_candidates.append(next_at)

        reminder_can_act = role in WRITE_ROLES
        reminder_dicts.append({
            **r.to_dict(),
            "can_edit": can_delete_record(role, r.created_by_user_id, user_id),
            "can_delete": can_delete_record(role, r.created_by_user_id, user_id),
            "can_act": reminder_can_act,
            "next_occurrence_at": (next_at.isoformat() + "+07:00") if next_at else None,
            "occurrences": [_occurrence_to_json(o, reminder_can_act, date_range) for o in occurrences],
        })

    next_upcoming_at = min(next_upcoming_candidates) if next_upcoming_candidates else None

    return jsonify({
        "child_id": child_id,
        "timezone": "Asia/Jakarta",
        "server_time": now.isoformat() + "+07:00",
        "reminders": reminder_dicts,
        "summary": {
            "due_count": due_count,
            "overdue_count": overdue_count,
            "next_upcoming_at": (next_upcoming_at.isoformat() + "+07:00") if next_upcoming_at else None,
        },
    })


@reminder_bp.route("/children/<int:child_id>/reminders", methods=["POST"])
def create_reminder(child_id):
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()
    if resolve_role(child, user_id) not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Format data tidak valid"}), 400

    error = _validate_reminder_payload(data, partial=False)
    if error:
        return jsonify({"error": error}), 400

    client_request_id = request.headers.get("X-Idempotency-Key")
    fingerprint = compute_fingerprint(data)

    def build():
        reminder = Reminder(
            child_id=child_id,
            created_by_user_id=user_id,
            reminder_type=data["reminder_type"],
            title=data["title"].strip(),
            scheduled_at=to_wib_naive(data["scheduled_at"]),
            recurrence=data.get("recurrence", "none"),
            is_active=True,
        )
        db.session.add(reminder)
        db.session.flush()
        record_audit_event(
            child_id=child_id, actor_user_id=user_id, action="create",
            entity_type="reminder", entity_id=reminder.id, recorded_at=reminder.scheduled_at,
        )
        return reminder.to_dict()

    body, status, _ = idempotent_create(user_id, child_id, "reminders", client_request_id, fingerprint, build)
    return jsonify(body), status


# --------------------------------------------------------------------------
# PATCH / DELETE /children/<child_id>/reminders/<reminder_id>
# --------------------------------------------------------------------------

@reminder_bp.route("/children/<int:child_id>/reminders/<int:reminder_id>", methods=["PATCH"])
def update_reminder(child_id, reminder_id):
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()

    # `filter_by(id=..., child_id=...)` SEKALIGUS -- reminder yang id-nya
    # cocok tapi child_id-nya BEDA (punya anak lain) balik 404, PERSIS
    # kayak yang beneran nggak ada (cegah IDOR lintas anak).
    reminder = Reminder.query.filter_by(id=reminder_id, child_id=child_id).first()
    if not reminder:
        return jsonify({"error": REMINDER_NOT_FOUND_MESSAGE}), 404

    role = resolve_role(child, user_id)
    if not can_delete_record(role, reminder.created_by_user_id, user_id):
        return jsonify({"error": NO_EDIT_PERMISSION_MESSAGE}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Format data tidak valid"}), 400

    error = _validate_reminder_payload(data, partial=True)
    if error:
        return jsonify({"error": error}), 400

    before = snapshot_fields(reminder, "reminder")
    if "reminder_type" in data:
        reminder.reminder_type = data["reminder_type"]
    if "title" in data:
        reminder.title = data["title"].strip()
    if "scheduled_at" in data:
        reminder.scheduled_at = to_wib_naive(data["scheduled_at"])
    if "recurrence" in data:
        reminder.recurrence = data["recurrence"]
    if "is_active" in data:
        reminder.is_active = data["is_active"]

    changed = diff_snapshots(before, snapshot_fields(reminder, "reminder"), "reminder")
    if changed:
        record_audit_event(
            child_id=child_id, actor_user_id=user_id, action="update",
            entity_type="reminder", entity_id=reminder.id, changed_fields=changed, recorded_at=reminder.scheduled_at,
        )
    db.session.commit()
    return jsonify(reminder.to_dict())


@reminder_bp.route("/children/<int:child_id>/reminders/<int:reminder_id>", methods=["DELETE"])
def delete_reminder(child_id, reminder_id):
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()

    reminder = Reminder.query.filter_by(id=reminder_id, child_id=child_id).first()
    if not reminder:
        return jsonify({"error": REMINDER_NOT_FOUND_MESSAGE}), 404

    role = resolve_role(child, user_id)
    if not can_delete_record(role, reminder.created_by_user_id, user_id):
        return jsonify({"error": NO_DELETE_PERMISSION_MESSAGE}), 403

    record_audit_event(
        child_id=child_id, actor_user_id=user_id, action="delete",
        entity_type="reminder", entity_id=reminder.id, recorded_at=reminder.scheduled_at,
    )
    db.session.delete(reminder)
    db.session.commit()
    return jsonify({"success": True})


# --------------------------------------------------------------------------
# POST .../occurrences/<occurrence_key>/complete | /skip
#
# Idempotensi 2 LAPIS (sengaja terpisah dari utils/idempotency.py:
# idempotent_create() yang generik -- itu cuma tau 1 sumbu keunikan,
# client_request_id; di sini ADA sumbu keunikan KEDUA yang independen:
# 1 okurensi cuma boleh punya SATU aksi, terlepas dari idempotency key
# apa pun yang dipakai):
#   1. client_request_id yang SAMA diulang (retry/replay antrian offline)
#      -> balikin respons ASLI yang udah kesimpen, TIDAK bikin baris baru.
#   2. Okurensi yang SAMA (reminder_id + occurrence_at) diaksi dari
#      client_request_id yang BEDA (klik dobel yang bikin 2 idempotency
#      key beda, ATAU 2 caregiver beda-beda meng-klik hampir bersamaan)
#      -> 409, TIDAK PERNAH menimpa aksi yang udah ada.
# --------------------------------------------------------------------------

def _act_on_occurrence(child_id, reminder_id, occurrence_key, status, endpoint_name):
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()

    reminder = Reminder.query.filter_by(id=reminder_id, child_id=child_id).first()
    if not reminder:
        return jsonify({"error": REMINDER_NOT_FOUND_MESSAGE}), 404

    role = resolve_role(child, user_id)
    if role not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    if not reminder.is_active:
        return jsonify({"error": "Pengingat ini sudah nonaktif"}), 400

    occ_date = parse_occurrence_key(occurrence_key)
    if occ_date is None:
        return jsonify({"error": "Format occurrence_key tidak valid, harus YYYY-MM-DD"}), 400

    today = now_wib().date()
    date_range = valid_occurrence_date_range(reminder.scheduled_at, reminder.recurrence, today)
    # `None` = TIDAK ADA tanggal yang sah diaksi sama sekali right now
    # (mis. reminder 'none' yang jadwalnya sendiri masih di masa depan,
    # ATAU reminder 'daily' yang belum sampai tanggal mulainya) -- WAJIB
    # ditolak SEBELUM unpacking, requirement review: "future one-time
    # occurrence must not be acted on early".
    if date_range is None:
        return jsonify({"error": "Okurensi ini di luar jangkauan yang bisa diaksi"}), 400
    earliest, latest = date_range
    if not (earliest <= occ_date <= latest):
        return jsonify({"error": "Okurensi ini di luar jangkauan yang bisa diaksi"}), 400

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Format data tidak valid"}), 400

    linked_log_type = data.get("linked_log_type")
    linked_log_id = data.get("linked_log_id")
    if linked_log_type is not None:
        if linked_log_type not in LINKABLE_LOG_TYPES:
            return jsonify({"error": f"linked_log_type harus salah satu dari: {', '.join(LINKABLE_LOG_TYPES)}"}), 400
        if not isinstance(linked_log_id, int):
            return jsonify({"error": "linked_log_id wajib diisi (angka) kalau linked_log_type dikirim"}), 400
        if not _log_belongs_to_child(linked_log_type, linked_log_id, child_id):
            return jsonify({"error": "Catatan yang ditautkan tidak ditemukan"}), 400

    occurrence_at = occurrence_datetime_for_date(reminder.scheduled_at, occ_date)

    client_request_id = request.headers.get("X-Idempotency-Key")
    fingerprint = compute_fingerprint({
        "reminder_id": reminder_id, "occurrence_key": occurrence_key,
        "linked_log_type": linked_log_type, "linked_log_id": linked_log_id,
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
        existing_action = ReminderAction.query.filter_by(reminder_id=reminder_id, occurrence_at=occurrence_at).first()
        if not existing_action:
            return None
        return jsonify({
            "error": "Okurensi ini sudah pernah diselesaikan/dilewati sebelumnya.",
            "current_status": existing_action.status,
        }), 409

    conflict = _occurrence_conflict()
    if conflict:
        return conflict

    action = ReminderAction(
        reminder_id=reminder_id,
        occurrence_at=occurrence_at,
        status=status,
        acted_at=now_wib(),
        acted_by_user_id=user_id,
        linked_log_type=linked_log_type,
        linked_log_id=linked_log_id,
    )
    db.session.add(action)
    db.session.flush()

    entity_type = (
        REMINDER_OCCURRENCE_COMPLETED_ENTITY_TYPE if status == "completed"
        else REMINDER_OCCURRENCE_SKIPPED_ENTITY_TYPE
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
        # Race genuine (2 request nyampe hampir bersamaan) -- entah sisi
        # idempotency key ATAUPUN sisi keunikan okurensi yang kena
        # duluan; DUA-duanya dicek ulang di sini, TIDAK PERNAH nge-crash
        # jadi 500 buat kasus yang SEBENARNYA konflik biasa (bukan bug).
        db.session.rollback()
        replay = _existing_replay()
        if replay:
            return replay
        conflict = _occurrence_conflict()
        if conflict:
            return conflict
        raise

    return jsonify(body), 201


@reminder_bp.route(
    "/children/<int:child_id>/reminders/<int:reminder_id>/occurrences/<occurrence_key>/complete",
    methods=["POST"],
)
def complete_occurrence(child_id, reminder_id, occurrence_key):
    return _act_on_occurrence(child_id, reminder_id, occurrence_key, "completed", "reminder-occurrence-complete")


@reminder_bp.route(
    "/children/<int:child_id>/reminders/<int:reminder_id>/occurrences/<occurrence_key>/skip",
    methods=["POST"],
)
def skip_occurrence(child_id, reminder_id, occurrence_key):
    return _act_on_occurrence(child_id, reminder_id, occurrence_key, "skipped", "reminder-occurrence-skip")
