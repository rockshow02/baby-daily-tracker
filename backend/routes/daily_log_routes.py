from datetime import datetime, timedelta
from sqlalchemy import or_
from utils.timezone_utils import now_wib, today_wib, to_wib_naive
from flask import Blueprint, request, jsonify, session

from extensions import db
from models import Child, FeedingLog, SleepLog, DiaperLog, User, WakeWindowGuideline
from utils.telegram import notify_other_caregivers
from utils.access import get_accessible_child, resolve_role, can_delete_record, WRITE_ROLES
from utils.auth import get_current_user_id
from utils.idempotency import idempotent_create, compute_fingerprint
from utils.summary_engine import build_daily_summary, get_age_in_days
from utils.audit import record_audit_event, snapshot_fields, diff_snapshots

daily_log_bp = Blueprint("daily_log", __name__)

# Caregiver Roles & Permissions Phase 1 (lihat backend/docs/ROLES_PERMISSIONS.md)
# — pesan 403 dipakai SERAGAM di semua route create/update/delete di file
# ini (dan file route log lainnya), biar perilakunya gampang diaudit dan
# dites, bukan pesan ad-hoc beda-beda per route.
NO_WRITE_ROLE_MESSAGE = "Peran Anda hanya bisa melihat data, tidak bisa menambah/mengubah catatan."
NO_DELETE_PERMISSION_MESSAGE = "Anda tidak punya izin untuk menghapus catatan ini."


def _get_owned_child_or_none(child_id):
    user_id = get_current_user_id()
    if not user_id:
        return None
    return get_accessible_child(child_id, user_id)


def _parse_date_param():
    date_str = request.args.get("date")
    if date_str:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    return today_wib()


# ---------- FEEDING ----------

@daily_log_bp.route("/children/<int:child_id>/feeding-logs", methods=["GET"])
def list_feeding_logs(child_id):
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    target_date = _parse_date_param()
    logs = (
        FeedingLog.query.filter(
            FeedingLog.child_id == child_id,
            db.func.date(FeedingLog.timestamp) == target_date,
        )
        .order_by(FeedingLog.timestamp.desc())
        .all()
    )
    return jsonify([log.to_dict() for log in logs])


@daily_log_bp.route("/children/<int:child_id>/feeding-logs", methods=["POST"])
def create_feeding_log(child_id):
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    user_id = get_current_user_id()
    if resolve_role(child, user_id) not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    data = request.get_json() or {}
    if not data.get("feed_type"):
        return jsonify({"error": "feed_type wajib diisi"}), 400

    client_request_id = request.headers.get("X-Idempotency-Key")
    fingerprint = compute_fingerprint(data)

    def build():
        log = FeedingLog(
            created_by_user_id=user_id,
            child_id=child_id,
            timestamp=to_wib_naive(data["timestamp"]) if data.get("timestamp") else now_wib(),
            feed_type=data["feed_type"],
            duration_minutes=data.get("duration_minutes"),
            volume_ml=data.get("volume_ml"),
            breast_side=data.get("breast_side"),
            notes=data.get("notes"),
        )
        db.session.add(log)
        db.session.flush()
        record_audit_event(
            child_id=child_id, actor_user_id=user_id, action="create",
            entity_type="feeding_log", entity_id=log.id, recorded_at=log.timestamp,
        )
        return log.to_dict()

    def send_notification():
        notify_other_caregivers(child, user_id, f"🍼 {User.query.get(user_id).name} mencatat menyusui untuk {child.nickname or child.name}.")

    body, status, _ = idempotent_create(
        user_id, child_id, "feeding-logs", client_request_id, fingerprint, build, after_commit=send_notification
    )
    return jsonify(body), status


@daily_log_bp.route("/feeding-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_feeding_log(log_id):
    log = FeedingLog.query.get_or_404(log_id)
    child = _get_owned_child_or_none(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    user_id = get_current_user_id()
    role = resolve_role(child, user_id)

    if request.method == "DELETE":
        if not can_delete_record(role, log.created_by_user_id, user_id):
            return jsonify({"error": NO_DELETE_PERMISSION_MESSAGE}), 403
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="delete",
            entity_type="feeding_log", entity_id=log.id, recorded_at=log.timestamp,
        )
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    if role not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    data = request.get_json() or {}
    before = snapshot_fields(log, "feeding_log")
    for field in ["feed_type", "duration_minutes", "volume_ml", "breast_side", "notes"]:
        if field in data:
            setattr(log, field, data[field])
    if "timestamp" in data:
        log.timestamp = to_wib_naive(data["timestamp"])
    changed = diff_snapshots(before, snapshot_fields(log, "feeding_log"), "feeding_log")
    if changed:
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="update",
            entity_type="feeding_log", entity_id=log.id, changed_fields=changed, recorded_at=log.timestamp,
        )
    db.session.commit()
    return jsonify(log.to_dict())


# ---------- SLEEP ----------

@daily_log_bp.route("/children/<int:child_id>/sleep-logs", methods=["GET"])
def list_sleep_logs(child_id):
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    target_date = _parse_date_param()
    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    # Sesi tidur yang lintas tengah malam (mis. mulai jam 20:00 kemarin,
    # baru selesai jam 05:00 hari ini) harus muncul di KEDUA hari yang
    # terkait, bukan cuma di hari mulainya doang — makanya query di sini
    # nyari sesi yang OVERLAP sama rentang hari ini, bukan cuma yang
    # start_time-nya persis di hari ini.
    logs = (
        SleepLog.query.filter(
            SleepLog.child_id == child_id,
            SleepLog.start_time < day_end,
            or_(SleepLog.end_time.is_(None), SleepLog.end_time > day_start),
        )
        .order_by(SleepLog.start_time.desc())
        .all()
    )
    return jsonify([log.to_dict() for log in logs])


@daily_log_bp.route("/children/<int:child_id>/sleep-logs", methods=["POST"])
def create_sleep_log(child_id):
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    user_id = get_current_user_id()
    if resolve_role(child, user_id) not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    data = request.get_json() or {}
    if not data.get("start_time"):
        return jsonify({"error": "start_time wajib diisi"}), 400

    client_request_id = request.headers.get("X-Idempotency-Key")
    fingerprint = compute_fingerprint(data)

    def build():
        log = SleepLog(
            created_by_user_id=user_id,
            child_id=child_id,
            start_time=to_wib_naive(data["start_time"]),
            end_time=to_wib_naive(data["end_time"]) if data.get("end_time") else None,
            sleep_type=data.get("sleep_type", "siang"),
            notes=data.get("notes"),
        )
        db.session.add(log)
        db.session.flush()
        record_audit_event(
            child_id=child_id, actor_user_id=user_id, action="create",
            entity_type="sleep_log", entity_id=log.id, recorded_at=log.start_time,
        )
        return log.to_dict()

    def send_notification():
        notify_other_caregivers(child, user_id, f"😴 {User.query.get(user_id).name} mencatat tidur untuk {child.nickname or child.name}.")

    body, status, _ = idempotent_create(
        user_id, child_id, "sleep-logs", client_request_id, fingerprint, build, after_commit=send_notification
    )
    return jsonify(body), status


@daily_log_bp.route("/sleep-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_sleep_log(log_id):
    log = SleepLog.query.get_or_404(log_id)
    child = _get_owned_child_or_none(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    user_id = get_current_user_id()
    role = resolve_role(child, user_id)

    if request.method == "DELETE":
        if not can_delete_record(role, log.created_by_user_id, user_id):
            return jsonify({"error": NO_DELETE_PERMISSION_MESSAGE}), 403
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="delete",
            entity_type="sleep_log", entity_id=log.id, recorded_at=log.start_time,
        )
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    if role not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    data = request.get_json() or {}
    before = snapshot_fields(log, "sleep_log")
    if "end_time" in data:
        log.end_time = to_wib_naive(data["end_time"]) if data["end_time"] else None
    if "sleep_type" in data:
        log.sleep_type = data["sleep_type"]
    if "notes" in data:
        log.notes = data["notes"]
    changed = diff_snapshots(before, snapshot_fields(log, "sleep_log"), "sleep_log")
    if changed:
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="update",
            entity_type="sleep_log", entity_id=log.id, changed_fields=changed, recorded_at=log.start_time,
        )
    db.session.commit()
    return jsonify(log.to_dict())


# ---------- DIAPER ----------

@daily_log_bp.route("/children/<int:child_id>/diaper-logs", methods=["GET"])
def list_diaper_logs(child_id):
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    target_date = _parse_date_param()
    logs = (
        DiaperLog.query.filter(
            DiaperLog.child_id == child_id,
            db.func.date(DiaperLog.timestamp) == target_date,
        )
        .order_by(DiaperLog.timestamp.desc())
        .all()
    )
    return jsonify([log.to_dict() for log in logs])


@daily_log_bp.route("/children/<int:child_id>/diaper-logs", methods=["POST"])
def create_diaper_log(child_id):
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    user_id = get_current_user_id()
    if resolve_role(child, user_id) not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    data = request.get_json() or {}
    if not data.get("diaper_type"):
        return jsonify({"error": "diaper_type wajib diisi"}), 400

    client_request_id = request.headers.get("X-Idempotency-Key")
    fingerprint = compute_fingerprint(data)

    def build():
        log = DiaperLog(
            created_by_user_id=user_id,
            child_id=child_id,
            timestamp=to_wib_naive(data["timestamp"]) if data.get("timestamp") else now_wib(),
            diaper_type=data["diaper_type"],
            consistency=data.get("consistency"),
            color=data.get("color"),
            notes=data.get("notes"),
        )
        db.session.add(log)
        db.session.flush()
        record_audit_event(
            child_id=child_id, actor_user_id=user_id, action="create",
            entity_type="diaper_log", entity_id=log.id, recorded_at=log.timestamp,
        )
        return log.to_dict()

    def send_notification():
        notify_other_caregivers(child, user_id, f"👶 {User.query.get(user_id).name} mencatat ganti popok untuk {child.nickname or child.name}.")

    body, status, _ = idempotent_create(
        user_id, child_id, "diaper-logs", client_request_id, fingerprint, build, after_commit=send_notification
    )
    return jsonify(body), status


@daily_log_bp.route("/diaper-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_diaper_log(log_id):
    log = DiaperLog.query.get_or_404(log_id)
    child = _get_owned_child_or_none(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    user_id = get_current_user_id()
    role = resolve_role(child, user_id)

    if request.method == "DELETE":
        if not can_delete_record(role, log.created_by_user_id, user_id):
            return jsonify({"error": NO_DELETE_PERMISSION_MESSAGE}), 403
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="delete",
            entity_type="diaper_log", entity_id=log.id, recorded_at=log.timestamp,
        )
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    if role not in WRITE_ROLES:
        return jsonify({"error": NO_WRITE_ROLE_MESSAGE}), 403

    data = request.get_json() or {}
    before = snapshot_fields(log, "diaper_log")
    if "timestamp" in data:
        log.timestamp = to_wib_naive(data["timestamp"])
    if "diaper_type" in data:
        log.diaper_type = data["diaper_type"]
    if "consistency" in data:
        log.consistency = data["consistency"]
    if "color" in data:
        log.color = data["color"]
    if "notes" in data:
        log.notes = data["notes"]
    changed = diff_snapshots(before, snapshot_fields(log, "diaper_log"), "diaper_log")
    if changed:
        record_audit_event(
            child_id=log.child_id, actor_user_id=user_id, action="update",
            entity_type="diaper_log", entity_id=log.id, changed_fields=changed, recorded_at=log.timestamp,
        )
    db.session.commit()
    return jsonify(log.to_dict())


# ---------- DAILY SUMMARY ----------

@daily_log_bp.route("/children/<int:child_id>/daily-summary", methods=["GET"])
def daily_summary(child_id):
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    target_date = _parse_date_param()

    feeding_count = FeedingLog.query.filter(
        FeedingLog.child_id == child_id,
        db.func.date(FeedingLog.timestamp) == target_date,
    ).count()

    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    sleep_logs = SleepLog.query.filter(
        SleepLog.child_id == child_id,
        SleepLog.start_time < day_end,
        or_(SleepLog.end_time.is_(None), SleepLog.end_time > day_start),
    ).all()

    # tiap sesi dipotong (clip) ke rentang hari ini doang, biar sesi yang
    # lintas tengah malam nggak dihitung dobel di 2 hari atau malah hilang
    # sama sekali dari salah satu harinya
    sleep_minutes = 0
    for log in sleep_logs:
        seg_start = max(log.start_time, day_start)
        seg_end = min(log.end_time, day_end) if log.end_time else min(now_wib(), day_end)
        if seg_end > seg_start:
            sleep_minutes += (seg_end - seg_start).total_seconds() / 60
    sleep_hours = round(sleep_minutes / 60, 1)

    wet_diaper_count = DiaperLog.query.filter(
        DiaperLog.child_id == child_id,
        db.func.date(DiaperLog.timestamp) == target_date,
        DiaperLog.diaper_type.in_(["pipis", "keduanya"]),
    ).count()

    bab_count = DiaperLog.query.filter(
        DiaperLog.child_id == child_id,
        db.func.date(DiaperLog.timestamp) == target_date,
        DiaperLog.diaper_type.in_(["pup", "keduanya"]),
    ).count()

    summary = build_daily_summary(
        child=child,
        on_date=target_date,
        feeding_count=feeding_count,
        sleep_hours=sleep_hours,
        wet_diaper_count=wet_diaper_count,
        bab_count=bab_count,
    )
    return jsonify(summary)


@daily_log_bp.route("/children/<int:child_id>/feeding-prediction", methods=["GET"])
def feeding_prediction(child_id):
    """
    Prediksi jam menyusui berikutnya, dihitung dari rata-rata interval
    antar sesi menyusui terakhir (maksimal 8 sesi terakhir dalam 48 jam).
    """
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    cutoff = now_wib() - timedelta(hours=48)
    recent_logs = (
        FeedingLog.query.filter(
            FeedingLog.child_id == child_id,
            FeedingLog.timestamp >= cutoff,
        )
        .order_by(FeedingLog.timestamp.desc())
        .limit(8)
        .all()
    )
    recent_logs = list(reversed(recent_logs))  # urutkan lama -> baru

    if len(recent_logs) < 2:
        return jsonify({
            "has_prediction": False,
            "message": "Belum cukup data (minimal 2 catatan menyusui dalam 48 jam terakhir).",
        })

    intervals_minutes = []
    for i in range(1, len(recent_logs)):
        delta = recent_logs[i].timestamp - recent_logs[i - 1].timestamp
        intervals_minutes.append(delta.total_seconds() / 60)

    avg_interval = sum(intervals_minutes) / len(intervals_minutes)
    last_feeding = recent_logs[-1]
    predicted_next = last_feeding.timestamp + timedelta(minutes=avg_interval)

    minutes_until_next = (predicted_next - now_wib()).total_seconds() / 60

    return jsonify({
        "has_prediction": True,
        "last_feeding_at": last_feeding.timestamp.isoformat() + "+07:00",
        "average_interval_minutes": round(avg_interval),
        "predicted_next_at": predicted_next.isoformat() + "+07:00",
        "minutes_until_next": round(minutes_until_next),
        "is_overdue": minutes_until_next < 0,
        "sample_size": len(recent_logs),
    })


@daily_log_bp.route("/children/<int:child_id>/wake-window-prediction", methods=["GET"])
def wake_window_prediction(child_id):
    """
    Prediksi kapan bayi kemungkinan mulai ngantuk lagi, berdasarkan acuan
    "wake window" (rentang waktu terjaga yang umum) sesuai usia — BUKAN
    dari rata-rata interval kayak feeding_prediction, karena wake window
    itu emang lebih ke acuan tumbuh kembang standar per usia.
    """
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    last_sleep = SleepLog.query.filter_by(child_id=child_id).order_by(SleepLog.start_time.desc()).first()

    if not last_sleep:
        return jsonify({
            "has_prediction": False,
            "message": "Belum ada catatan tidur sama sekali.",
        })

    if not last_sleep.end_time:
        return jsonify({
            "has_prediction": False,
            "is_currently_sleeping": True,
            "sleep_started_at": last_sleep.start_time.isoformat() + "+07:00",
            "message": "Lagi tidur sekarang.",
        })

    age_days = get_age_in_days(child.birth_date, today_wib())
    guideline = (
        WakeWindowGuideline.query.filter(
            WakeWindowGuideline.age_min_days <= age_days,
            WakeWindowGuideline.age_max_days >= age_days,
        )
        .first()
    )

    if not guideline:
        return jsonify({
            "has_prediction": False,
            "message": "Belum ada acuan wake window buat usia ini.",
        })

    last_wake_at = last_sleep.end_time
    predicted_min = last_wake_at + timedelta(minutes=guideline.min_wake_minutes)
    predicted_max = last_wake_at + timedelta(minutes=guideline.max_wake_minutes)
    now = now_wib()

    minutes_until_min = (predicted_min - now).total_seconds() / 60
    minutes_until_max = (predicted_max - now).total_seconds() / 60

    return jsonify({
        "has_prediction": True,
        "is_currently_sleeping": False,
        "last_wake_at": last_wake_at.isoformat() + "+07:00",
        "predicted_min_at": predicted_min.isoformat() + "+07:00",
        "predicted_max_at": predicted_max.isoformat() + "+07:00",
        "minutes_until_min": round(minutes_until_min),
        "minutes_until_max": round(minutes_until_max),
        "is_overdue": minutes_until_max < 0,
        "is_in_window": minutes_until_min <= 0 <= minutes_until_max,
        "guideline_label": guideline.label,
    })