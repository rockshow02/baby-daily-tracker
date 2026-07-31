from datetime import datetime, timedelta
from collections import defaultdict

from flask import Blueprint, request, jsonify, session

from models import (
    Child, FeedingLog, SleepLog, DiaperLog, PumpingLog, ActivityLog, MoodLog,
)
from utils.access import get_accessible_child
from utils.auth import get_current_user_id
from utils.timezone_utils import today_wib

stats_bp = Blueprint("stats", __name__)


def _owned_child(child_id):
    user_id = get_current_user_id()
    if not user_id:
        return None
    return get_accessible_child(child_id, user_id)


@stats_bp.route("/children/<int:child_id>/stats", methods=["GET"])
def get_stats(child_id):
    """
    Statistik & tren dalam rentang N hari terakhir (default 7, maks 90).
    Query param: days=7 | 30 | 90
    """
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    try:
        days = int(request.args.get("days", 7))
    except ValueError:
        days = 7
    days = max(1, min(days, 90))

    end_date = today_wib()
    start_date = end_date - timedelta(days=days - 1)

    # siapin bucket kosong per tanggal biar chart nggak bolong
    buckets = {}
    d = start_date
    while d <= end_date:
        buckets[d.isoformat()] = {
            "date": d.isoformat(),
            "feeding_count": 0,
            "sleep_hours": 0.0,
            "wet_diaper_count": 0,
            "dirty_diaper_count": 0,
            "pumping_count": 0,
            "pumping_volume_ml": 0,
            "stroll_count": 0,
            "bathing_count": 0,
        }
        d += timedelta(days=1)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())

    # feeding
    feeding_logs = FeedingLog.query.filter(
        FeedingLog.child_id == child_id,
        FeedingLog.timestamp >= start_dt,
        FeedingLog.timestamp <= end_dt,
    ).all()
    for log in feeding_logs:
        key = log.timestamp.date().isoformat()
        if key in buckets:
            buckets[key]["feeding_count"] += 1

    # sleep (durasi dihitung di Python karena end_time bisa null / properti)
    sleep_logs = SleepLog.query.filter(
        SleepLog.child_id == child_id,
        SleepLog.start_time >= start_dt,
        SleepLog.start_time <= end_dt,
    ).all()
    for log in sleep_logs:
        key = log.start_time.date().isoformat()
        if key in buckets and log.duration_minutes:
            buckets[key]["sleep_hours"] += log.duration_minutes / 60

    # diaper
    diaper_logs = DiaperLog.query.filter(
        DiaperLog.child_id == child_id,
        DiaperLog.timestamp >= start_dt,
        DiaperLog.timestamp <= end_dt,
    ).all()
    for log in diaper_logs:
        key = log.timestamp.date().isoformat()
        if key not in buckets:
            continue
        if log.diaper_type in ("pipis", "keduanya"):
            buckets[key]["wet_diaper_count"] += 1
        if log.diaper_type in ("pup", "keduanya"):
            buckets[key]["dirty_diaper_count"] += 1

    # pumping
    pumping_logs = PumpingLog.query.filter(
        PumpingLog.child_id == child_id,
        PumpingLog.timestamp >= start_dt,
        PumpingLog.timestamp <= end_dt,
    ).all()
    for log in pumping_logs:
        key = log.timestamp.date().isoformat()
        if key in buckets:
            buckets[key]["pumping_count"] += 1
            buckets[key]["pumping_volume_ml"] += log.volume_ml or 0

    # activity
    activity_logs = ActivityLog.query.filter(
        ActivityLog.child_id == child_id,
        ActivityLog.timestamp >= start_dt,
        ActivityLog.timestamp <= end_dt,
    ).all()
    for log in activity_logs:
        key = log.timestamp.date().isoformat()
        if key not in buckets:
            continue
        if log.activity_type == "stroll":
            buckets[key]["stroll_count"] += 1
        elif log.activity_type == "bathing":
            buckets[key]["bathing_count"] += 1

    # mood distribution (agregat sepanjang periode, bukan per hari)
    mood_logs = MoodLog.query.filter(
        MoodLog.child_id == child_id,
        MoodLog.timestamp >= start_dt,
        MoodLog.timestamp <= end_dt,
    ).all()
    mood_counts = defaultdict(int)
    for log in mood_logs:
        mood_counts[log.mood] += 1

    days_list = [buckets[k] for k in sorted(buckets.keys())]
    for day in days_list:
        day["sleep_hours"] = round(day["sleep_hours"], 1)

    n = len(days_list) or 1
    averages = {
        "feeding_per_day": round(sum(d["feeding_count"] for d in days_list) / n, 1),
        "sleep_hours_per_day": round(sum(d["sleep_hours"] for d in days_list) / n, 1),
        "wet_diaper_per_day": round(sum(d["wet_diaper_count"] for d in days_list) / n, 1),
        "dirty_diaper_per_day": round(sum(d["dirty_diaper_count"] for d in days_list) / n, 1),
    }

    return jsonify({
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days": days_list,
        "averages": averages,
        "mood_distribution": dict(mood_counts),
        "total_records": len(feeding_logs) + len(sleep_logs) + len(diaper_logs),
    })