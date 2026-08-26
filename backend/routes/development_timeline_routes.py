"""Development Timeline read-only: agregasi bounded tanpa menduplikasi data."""
from datetime import date, datetime, time

from flask import Blueprint, jsonify, request

from models import (ChildVaccination, DoctorVisitLog, GrowthMeasurement, IllnessLog,
                    MemoryJournalEntry, MilestoneLog, TemperatureLog)
from utils.access import get_accessible_child
from utils.auth import get_current_user_id

development_timeline_bp = Blueprint("development_timeline", __name__)

CATEGORIES = {"memory", "milestone", "growth", "vaccination", "health", "doctor"}
MAX_LIMIT = 200


def _parse_optional_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("Format tanggal harus YYYY-MM-DD")


def _event(event_type, source_id, event_date, title, summary, icon, photo_entry_id=None):
    return {
        "id": f"{event_type}-{source_id}", "type": event_type, "source_id": source_id,
        "date": event_date.isoformat(), "title": title, "summary": summary,
        "icon": icon, "photo_entry_id": photo_entry_id,
    }


@development_timeline_bp.route("/children/<int:child_id>/development-timeline", methods=["GET"])
def development_timeline(child_id):
    user_id = get_current_user_id()
    child = get_accessible_child(child_id, user_id) if user_id else None
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404
    try:
        start = _parse_optional_date(request.args.get("from"))
        end = _parse_optional_date(request.args.get("to"))
        limit = min(MAX_LIMIT, max(1, int(request.args.get("limit", 100))))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc) if str(exc) else "Parameter tidak valid"}), 400
    if start and end and start > end:
        return jsonify({"error": "Tanggal awal tidak boleh setelah tanggal akhir"}), 400
    requested = {x.strip() for x in request.args.get("categories", "").split(",") if x.strip()}
    if requested - CATEGORIES:
        return jsonify({"error": "Kategori timeline tidak valid"}), 400
    categories = requested or CATEGORIES
    events = []

    def date_query(model, column):
        query = model.query.filter_by(child_id=child_id)
        if start: query = query.filter(column >= start)
        if end: query = query.filter(column <= end)
        return query.order_by(column.desc()).limit(MAX_LIMIT).all()

    if "memory" in categories:
        for row in date_query(MemoryJournalEntry, MemoryJournalEntry.occurred_date):
            events.append(_event("memory", row.id, row.occurred_date,
                row.caption or "Kenangan baru", "Foto privat keluarga", "📷", row.id))
            events[-1]["is_favorite"] = bool(row.metadata_record and row.metadata_record.is_favorite)
            events[-1]["tags"] = sorted(tag.tag for tag in row.tag_records)
    if "milestone" in categories:
        labels = {"bisa_duduk": "Bisa duduk", "langkah_pertama": "Langkah pertama",
                  "kata_pertama": "Kata pertama", "gigi_pertama": "Gigi pertama"}
        for row in date_query(MilestoneLog, MilestoneLog.achieved_date):
            title = row.custom_label if row.milestone_type == "custom" else labels.get(row.milestone_type, "Momen penting")
            events.append(_event("milestone", row.id, row.achieved_date, title, "Pencapaian perkembangan", "✨"))
    if "growth" in categories:
        for row in date_query(GrowthMeasurement, GrowthMeasurement.measured_date):
            parts = []
            if row.weight_kg is not None: parts.append(f"{row.weight_kg:g} kg")
            if row.height_cm is not None: parts.append(f"{row.height_cm:g} cm")
            if row.head_circumference_cm is not None: parts.append(f"lingkar kepala {row.head_circumference_cm:g} cm")
            events.append(_event("growth", row.id, row.measured_date, "Pengukuran pertumbuhan", " · ".join(parts), "📈"))
    if "vaccination" in categories:
        rows = date_query(ChildVaccination, ChildVaccination.given_date)
        for row in rows:
            if row.given and row.given_date:
                events.append(_event("vaccination", row.id, row.given_date,
                    row.vaccine.vaccine_name, row.vaccine.dose_label or "Vaksin diberikan", "💉"))
    if "health" in categories:
        for row in date_query(IllnessLog, IllnessLog.start_date):
            events.append(_event("health", row.id, row.start_date, "Catatan kesehatan",
                "Masih dipantau" if row.end_date is None else "Sudah selesai dipantau", "🩺"))
        query = TemperatureLog.query.filter_by(child_id=child_id)
        if start: query = query.filter(TemperatureLog.timestamp >= datetime.combine(start, time.min))
        if end: query = query.filter(TemperatureLog.timestamp <= datetime.combine(end, time.max))
        for row in query.order_by(TemperatureLog.timestamp.desc()).limit(MAX_LIMIT).all():
            events.append(_event("health", f"temperature-{row.id}", row.timestamp.date(),
                "Pemeriksaan suhu", f"{row.temperature_celsius:g} °C", "🌡️"))
    if "doctor" in categories:
        for row in date_query(DoctorVisitLog, DoctorVisitLog.visit_date):
            events.append(_event("doctor", row.id, row.visit_date, "Kunjungan dokter",
                "Kontrol berikutnya tercatat" if row.next_visit_date else "Catatan kunjungan", "👩‍⚕️"))

    events.sort(key=lambda item: (item["date"], item["id"]), reverse=True)
    return jsonify({"items": events[:limit], "has_more": len(events) > limit,
                    "categories": sorted(categories), "limit": limit})
