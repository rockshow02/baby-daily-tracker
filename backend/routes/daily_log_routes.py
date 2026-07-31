from datetime import datetime, timedelta
from utils.timezone_utils import now_wib, today_wib, to_wib_naive
from flask import Blueprint, request, jsonify, session

from extensions import db
from models import Child, FeedingLog, SleepLog, DiaperLog
from utils.access import get_accessible_child
from utils.summary_engine import build_daily_summary

daily_log_bp = Blueprint("daily_log", __name__)


def _get_owned_child_or_none(child_id):
    user_id = session.get("user_id")
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

    data = request.get_json() or {}
    if not data.get("feed_type"):
        return jsonify({"error": "feed_type wajib diisi"}), 400

    log = FeedingLog(
        child_id=child_id,
        timestamp=to_wib_naive(data["timestamp"]) if data.get("timestamp") else now_wib(),
        feed_type=data["feed_type"],
        duration_minutes=data.get("duration_minutes"),
        volume_ml=data.get("volume_ml"),
        breast_side=data.get("breast_side"),
        notes=data.get("notes"),
    )
    db.session.add(log)
    db.session.commit()
    return jsonify(log.to_dict()), 201


@daily_log_bp.route("/feeding-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_feeding_log(log_id):
    log = FeedingLog.query.get_or_404(log_id)
    child = _get_owned_child_or_none(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    if request.method == "DELETE":
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
    for field in ["feed_type", "duration_minutes", "volume_ml", "breast_side", "notes"]:
        if field in data:
            setattr(log, field, data[field])
    if "timestamp" in data:
        log.timestamp = to_wib_naive(data["timestamp"])
    db.session.commit()
    return jsonify(log.to_dict())


# ---------- SLEEP ----------

@daily_log_bp.route("/children/<int:child_id>/sleep-logs", methods=["GET"])
def list_sleep_logs(child_id):
    child = _get_owned_child_or_none(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    target_date = _parse_date_param()
    logs = (
        SleepLog.query.filter(
            SleepLog.child_id == child_id,
            db.func.date(SleepLog.start_time) == target_date,
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

    data = request.get_json() or {}
    if not data.get("start_time"):
        return jsonify({"error": "start_time wajib diisi"}), 400

    log = SleepLog(
        child_id=child_id,
        start_time=to_wib_naive(data["start_time"]),
        end_time=to_wib_naive(data["end_time"]) if data.get("end_time") else None,
        sleep_type=data.get("sleep_type", "siang"),
        notes=data.get("notes"),
    )
    db.session.add(log)
    db.session.commit()
    return jsonify(log.to_dict()), 201


@daily_log_bp.route("/sleep-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_sleep_log(log_id):
    log = SleepLog.query.get_or_404(log_id)
    child = _get_owned_child_or_none(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    if request.method == "DELETE":
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
    if "end_time" in data:
        log.end_time = to_wib_naive(data["end_time"]) if data["end_time"] else None
    if "sleep_type" in data:
        log.sleep_type = data["sleep_type"]
    if "notes" in data:
        log.notes = data["notes"]
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

    data = request.get_json() or {}
    if not data.get("diaper_type"):
        return jsonify({"error": "diaper_type wajib diisi"}), 400

    log = DiaperLog(
        child_id=child_id,
        timestamp=to_wib_naive(data["timestamp"]) if data.get("timestamp") else now_wib(),
        diaper_type=data["diaper_type"],
        consistency=data.get("consistency"),
        color=data.get("color"),
        notes=data.get("notes"),
    )
    db.session.add(log)
    db.session.commit()
    return jsonify(log.to_dict()), 201


@daily_log_bp.route("/diaper-logs/<int:log_id>", methods=["PUT", "DELETE"])
def update_or_delete_diaper_log(log_id):
    log = DiaperLog.query.get_or_404(log_id)
    child = _get_owned_child_or_none(log.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    if request.method == "DELETE":
        db.session.delete(log)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
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

    sleep_logs = SleepLog.query.filter(
        SleepLog.child_id == child_id,
        db.func.date(SleepLog.start_time) == target_date,
    ).all()
    sleep_minutes = sum(log.duration_minutes or 0 for log in sleep_logs)
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