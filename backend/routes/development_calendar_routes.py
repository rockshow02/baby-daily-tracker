"""Kalender perkembangan bulanan, read-only dan dihitung saat diminta."""
from calendar import monthrange
from collections import Counter
from datetime import date, datetime, time, timedelta

from flask import Blueprint, jsonify, request

from models import (AppointmentPreparation, ChildVaccination, DevelopmentGoal, DoctorVisitLog,
                    GrowthMeasurement, MedicationSchedule, MemoryJournalEntry,
                    MilestoneLog, Reminder)
from utils.access import get_accessible_child
from utils.auth import get_current_user_id

development_calendar_bp = Blueprint("development_calendar", __name__)

CATEGORIES = {"memory", "milestone", "growth", "vaccination", "doctor",
              "reminder", "medication", "goal"}
MAX_SOURCE_ROWS = 200


def _month_bounds(raw):
    try:
        parsed = datetime.strptime(raw or "", "%Y-%m")
    except ValueError:
        raise ValueError("Bulan harus berformat YYYY-MM")
    if not 2000 <= parsed.year <= 2100:
        raise ValueError("Tahun kalender harus antara 2000 dan 2100")
    start = date(parsed.year, parsed.month, 1)
    return start, date(parsed.year, parsed.month, monthrange(parsed.year, parsed.month)[1])


def _event(kind, source_id, event_date, title, summary, icon):
    return {"id": f"{kind}-{source_id}", "type": kind, "source_id": source_id,
            "date": event_date.isoformat(), "title": title, "summary": summary,
            "icon": icon}


@development_calendar_bp.route("/children/<int:child_id>/development-calendar", methods=["GET"])
def development_calendar(child_id):
    user_id = get_current_user_id()
    child = get_accessible_child(child_id, user_id) if user_id else None
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404
    try:
        start, end = _month_bounds(request.args.get("month"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    requested = {item.strip() for item in request.args.get("categories", "").split(",") if item.strip()}
    if requested - CATEGORIES:
        return jsonify({"error": "Kategori kalender tidak valid"}), 400
    categories = requested or CATEGORIES
    items = []

    def rows(model, column):
        return (model.query.filter(model.child_id == child_id, column >= start, column <= end)
                .order_by(column, model.id).limit(MAX_SOURCE_ROWS).all())

    if "memory" in categories:
        for row in rows(MemoryJournalEntry, MemoryJournalEntry.occurred_date):
            items.append(_event("memory", row.id, row.occurred_date,
                                row.caption or "Kenangan keluarga", "Foto privat keluarga", "📷"))
    if "milestone" in categories:
        labels = {"bisa_duduk": "Bisa duduk", "langkah_pertama": "Langkah pertama",
                  "kata_pertama": "Kata pertama", "gigi_pertama": "Gigi pertama"}
        for row in rows(MilestoneLog, MilestoneLog.achieved_date):
            title = row.custom_label if row.milestone_type == "custom" else labels.get(row.milestone_type, "Pencapaian baru")
            items.append(_event("milestone", row.id, row.achieved_date, title, "Pencapaian perkembangan", "✨"))
    if "growth" in categories:
        for row in rows(GrowthMeasurement, GrowthMeasurement.measured_date):
            items.append(_event("growth", row.id, row.measured_date, "Pengukuran pertumbuhan",
                                "Data tumbuh kembang diperbarui", "📈"))
    if "vaccination" in categories:
        for row in rows(ChildVaccination, ChildVaccination.given_date):
            if row.given:
                items.append(_event("vaccination", row.id, row.given_date, "Vaksinasi tercatat",
                                    "Detail tersedia di halaman kesehatan", "💉"))
    if "doctor" in categories:
        for row in rows(DoctorVisitLog, DoctorVisitLog.visit_date):
            items.append(_event("doctor", f"visit-{row.id}", row.visit_date, "Kunjungan dokter",
                                "Detail tersedia di halaman kesehatan", "🩺"))
        for row in rows(DoctorVisitLog, DoctorVisitLog.next_visit_date):
            if row.next_visit_date:
                items.append(_event("doctor", f"followup-{row.id}", row.next_visit_date,
                                    "Kontrol dokter terjadwal", "Jadwal kontrol berikutnya", "🩺"))
        for row in rows(AppointmentPreparation, AppointmentPreparation.appointment_date):
            items.append(_event("doctor", f"preparation-{row.id}", row.appointment_date,
                                "Persiapan konsultasi", "Checklist persiapan dokter", "✅"))
    if "goal" in categories:
        for row in rows(DevelopmentGoal, DevelopmentGoal.target_date):
            state = "Selesai" if row.completed_at else "Target keluarga"
            items.append(_event("goal", row.id, row.target_date, row.title, state, "🎯"))

    # Judul pengingat dan nama/dosis obat mungkin sensitif. Kalender hanya
    # mengirim jumlah agenda generik per hari, bukan nilai tersebut.
    if "reminder" in categories:
        counts = Counter()
        reminders = (Reminder.query.filter(Reminder.child_id == child_id, Reminder.is_active.is_(True),
                                            Reminder.scheduled_at <= datetime.combine(end, time.max))
                     .order_by(Reminder.id).limit(MAX_SOURCE_ROWS).all())
        for reminder in reminders:
            first = reminder.scheduled_at.date()
            if reminder.recurrence == "none":
                if start <= first <= end:
                    counts[first] += 1
                continue
            current = max(start, first)
            while current <= end:
                counts[current] += 1
                current += timedelta(days=1)
        for event_date, count in counts.items():
            items.append(_event("reminder", event_date.isoformat(), event_date, "Pengingat perawatan",
                                f"{count} pengingat terjadwal", "🔔"))
    if "medication" in categories:
        counts = Counter()
        schedules = (MedicationSchedule.query.filter(
            MedicationSchedule.child_id == child_id, MedicationSchedule.is_active.is_(True),
            MedicationSchedule.start_date <= end,
            (MedicationSchedule.end_date.is_(None)) | (MedicationSchedule.end_date >= start))
            .order_by(MedicationSchedule.id).limit(MAX_SOURCE_ROWS).all())
        for schedule in schedules:
            current = max(start, schedule.start_date)
            last = min(end, schedule.end_date) if schedule.end_date else end
            while current <= last:
                counts[current] += len(schedule.times_of_day or [])
                current += timedelta(days=1)
        for event_date, count in counts.items():
            items.append(_event("medication", event_date.isoformat(), event_date, "Jadwal obat",
                                f"{count} waktu pemberian terjadwal", "💊"))

    items.sort(key=lambda item: (item["date"], item["type"], item["id"]))
    return jsonify({"month": start.strftime("%Y-%m"), "month_start": start.isoformat(),
                    "month_end": end.isoformat(), "categories": sorted(categories),
                    "items": items,
                    "privacy_note": "Kalender umum tidak menampilkan nama obat, diagnosis, gejala, catatan, dokter, atau klinik."})
