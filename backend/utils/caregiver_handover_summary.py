"""
Caregiver Handover Summary — Phase 1 (lihat
backend/docs/CAREGIVER_HANDOVER.md buat kontrak lengkapnya).

Mesin MURNI-Python + query DB, TIDAK PERNAH memanggil jam sistem
sendiri — `window_start`/`as_of_at` SELALU dibaca dari
`CaregiverHandover` yang sudah dibekukan SEKALI saat handover dibuat
(lihat routes/caregiver_handover_routes.py), `generated_at` SELALU
parameter dari pemanggil (waktu SEKARANG saat ringkasan ini dibangun
ULANG buat ditampilkan — beda dari `as_of_at` yang BEKU). Persis
prinsip `utils/insights_engine.py`/`utils/reminder_engine.py`.

INI RINGKASAN OPERASIONAL, BUKAN Smart Insights (tren/perbandingan
periode) ATAUPUN Doctor Consultation (laporan buat dibawa ke dokter,
periode fleksibel 7-90 hari) — jendelanya SELALU TEPAT 24 jam
BERGULIR (bisa mulai jam berapa pun), dan isinya SELALU dihitung ULANG
dari tabel sumber, TIDAK PERNAH disalin/disimpan permanen ke
`caregiver_handovers`. TIDAK PERNAH mendiagnosis, TIDAK PERNAH label
"demam"/"normal"/"berbahaya", TIDAK PERNAH menyarankan tindakan medis
— CUMA merangkum APA yang caregiver sendiri sudah catat.

BEDA dari utils/insights_engine.py: modul itu meringkas per HARI
KALENDER WIB (tengah malam ke tengah malam), pas buat laporan
mingguan — TIDAK cocok buat jendela BERGULIR 24 jam PERSIS yang bisa
mulai jam berapa pun (mis. handover dibuat jam 14:30, jendelanya
[kemarin 14:30, hari ini 14:30]). Modul ini SENGAJA query LANGSUNG
rentang DATETIME [window_start, as_of_at] (inklusif dua-duanya, BUKAN
tanggal kalender) buat 6 kategori "harian" (feeding/sleep/diaper/
pumping/activity/mood), TAPI TETAP REUSE kebijakan kelengkapan nilai
terukur yang SAMA PERSIS
(`utils.insights_engine._measured_total_or_none`) — SATU sumber
kebenaran "kapan total boleh dipercaya", requirement eksplisit "reuse
existing conservative measured-value completeness helpers".

Medikasi & pengingat REUSE PENUH mesin yang sudah ada
(`utils.medication_schedule_engine`/`utils.reminder_engine`) — TIDAK
PERNAH menghitung ulang logika status/okurensi sendiri, DAN TIDAK
PERNAH memateri-alisasi okurensi masa depan jadi baris baru (SATU
sumber kebenaran per fitur, konsisten arsitektur "tanpa scheduler
background" PythonAnywhere Free).
"""
from datetime import time, timedelta

from models import (
    ActivityLog, DiaperLog, DoctorVisitLog, FeedingLog, IllnessLog,
    MedicationDoseAction, MedicationSchedule, MoodLog, PumpingLog, Reminder, ReminderAction, SleepLog,
    TemperatureLog,
)
from utils.insights_engine import _measured_total_or_none
from utils.medication_schedule_engine import (
    LOOKBACK_DAYS as MEDICATION_LOOKBACK_DAYS,
    compute_schedule_occurrences,
    next_actionable_occurrence_at,
)
from utils.reminder_engine import (
    DAILY_LOOKBACK_DAYS as REMINDER_LOOKBACK_DAYS,
    compute_reminder_occurrences,
    next_pending_occurrence_at,
)

DISCLAIMER = (
    "Serah terima ini merangkum catatan yang dimasukkan sendiri oleh caregiver dan BUKAN "
    "diagnosis, saran pengobatan, atau rekomendasi penanganan darurat."
)
PRIVACY_NOTE = (
    "Ringkasan ini berisi data perawatan anak yang cukup pribadi — bagikan hanya kepada "
    "caregiver lain yang memang perlu tahu."
)

# Batas baris ilness yang ditampilkan -- mencegah query/respons nggak
# terbatas buat anak dengan riwayat penyakit yang sangat panjang,
# konsisten pola row-cap SELURUH modul laporan lain di app ini
# (consultation_report.py dkk).
MAX_ILLNESS_ROWS = 10
MAX_MEDICATION_OVERDUE_ROWS = 10
MAX_MEDICATION_RESOLVED_ROWS = 10
MAX_REMINDER_OVERDUE_ROWS = 10
MAX_REMINDER_RESOLVED_ROWS = 10


def _iso_wib(dt):
    return dt.isoformat() + "+07:00" if dt else None


def _in_window(rows_query, column, window_start, as_of_at):
    return rows_query.filter(column >= window_start, column <= as_of_at)


def _feeding_section(child_id, window_start, as_of_at):
    rows = FeedingLog.query.filter(
        FeedingLog.child_id == child_id,
        FeedingLog.timestamp >= window_start,
        FeedingLog.timestamp <= as_of_at,
    ).order_by(FeedingLog.timestamp.desc(), FeedingLog.id.desc()).all()

    total_events = len(rows)
    latest = rows[0] if rows else None
    volumes = [r.volume_ml for r in rows if r.volume_ml is not None]
    measured_total_volume_ml = _measured_total_or_none(sum(volumes), total_events, len(volumes))

    return {
        "total_events": total_events,
        "latest_timestamp": _iso_wib(latest.timestamp) if latest else None,
        "latest_feed_type": latest.feed_type if latest else None,
        "latest_volume_ml": latest.volume_ml if latest else None,
        "measured_total_volume_ml": measured_total_volume_ml,
    }


def _sleep_section(child_id, window_start, as_of_at):
    rows = SleepLog.query.filter(
        SleepLog.child_id == child_id,
        SleepLog.start_time >= window_start,
        SleepLog.start_time <= as_of_at,
    ).order_by(SleepLog.start_time.desc(), SleepLog.id.desc()).all()

    total_events = len(rows)
    latest = rows[0] if rows else None
    # "ongoing" MURNI dari field yang TERCATAT (end_time IS NULL) --
    # TIDAK PERNAH menyimpulkan kualitas/kecukupan tidur medis apa pun
    # (requirement eksplisit: "do not infer medical sleep quality").
    latest_is_ongoing = bool(latest and latest.end_time is None)

    total_minutes = 0.0
    for r in rows:
        if r.end_time is None:
            continue
        minutes = (r.end_time - r.start_time).total_seconds() / 60
        if minutes < 0:
            continue  # data korup (end < start) -- dikecualikan, BUKAN bikin total negatif (pola sama insights_engine.py)
        total_minutes += minutes

    return {
        "total_events": total_events,
        "latest_start_time": _iso_wib(latest.start_time) if latest else None,
        "latest_end_time": _iso_wib(latest.end_time) if latest and latest.end_time else None,
        "latest_is_ongoing": latest_is_ongoing,
        "total_completed_minutes": round(total_minutes, 1),
    }


def _diaper_section(child_id, window_start, as_of_at):
    rows = DiaperLog.query.filter(
        DiaperLog.child_id == child_id,
        DiaperLog.timestamp >= window_start,
        DiaperLog.timestamp <= as_of_at,
    ).order_by(DiaperLog.timestamp.desc(), DiaperLog.id.desc()).all()

    latest = rows[0] if rows else None
    wet_count = sum(1 for r in rows if r.diaper_type in ("pipis", "keduanya"))
    dirty_count = sum(1 for r in rows if r.diaper_type in ("pup", "keduanya"))
    mixed_count = sum(1 for r in rows if r.diaper_type == "keduanya")

    return {
        "total_events": len(rows),
        "latest_timestamp": _iso_wib(latest.timestamp) if latest else None,
        "latest_diaper_type": latest.diaper_type if latest else None,
        "wet_count": wet_count,
        "dirty_count": dirty_count,
        "mixed_count": mixed_count,
    }


def _pumping_section(child_id, window_start, as_of_at):
    rows = PumpingLog.query.filter(
        PumpingLog.child_id == child_id,
        PumpingLog.timestamp >= window_start,
        PumpingLog.timestamp <= as_of_at,
    ).order_by(PumpingLog.timestamp.desc(), PumpingLog.id.desc()).all()

    total_events = len(rows)
    latest = rows[0] if rows else None
    volumes = [r.volume_ml for r in rows if r.volume_ml is not None]
    measured_total_volume_ml = _measured_total_or_none(sum(volumes), total_events, len(volumes))

    return {
        "total_events": total_events,
        "latest_timestamp": _iso_wib(latest.timestamp) if latest else None,
        "measured_total_volume_ml": measured_total_volume_ml,
    }


def _activity_mood_section(child_id, window_start, as_of_at):
    activity_rows = ActivityLog.query.filter(
        ActivityLog.child_id == child_id,
        ActivityLog.timestamp >= window_start,
        ActivityLog.timestamp <= as_of_at,
    ).order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc()).all()
    mood_rows = MoodLog.query.filter(
        MoodLog.child_id == child_id,
        MoodLog.timestamp >= window_start,
        MoodLog.timestamp <= as_of_at,
    ).order_by(MoodLog.timestamp.desc(), MoodLog.id.desc()).all()

    latest_activity = activity_rows[0] if activity_rows else None
    latest_mood = mood_rows[0] if mood_rows else None

    return {
        "activity_total_events": len(activity_rows),
        "latest_activity_type": latest_activity.activity_type if latest_activity else None,
        "latest_activity_timestamp": _iso_wib(latest_activity.timestamp) if latest_activity else None,
        "mood_total_events": len(mood_rows),
        "latest_mood": latest_mood.mood if latest_mood else None,
        "latest_mood_timestamp": _iso_wib(latest_mood.timestamp) if latest_mood else None,
    }


def _health_section(child_id, window_start, as_of_at):
    """
    `latest_temperature_*` SENGAJA di-scope KE JENDELA (beda dari
    convention "terbaru lifetime" di utils/insights_engine.py/
    utils/consultation_report.py) — handover ini soal "apa yang
    terjadi 24 jam terakhir", suhu dari berminggu-minggu lalu bakal
    menyesatkan kalau ditampilkan seolah masih relevan sekarang.

    `illnesses_overlapping_window` CUMA field STRUKTURAL (tanggal
    mulai/selesai/status berlangsung) — requirement eksplisit "using
    only safe structured fields" -- `illness_name` (identitas penyakit
    spesifik anak) TIDAK disertakan di sini SAMA SEKALI, konsisten sama
    `SAFE_CHANGED_FIELDS["illness_log"]` di utils/audit.py yang CUMA
    menganggap `start_date`/`end_date` "aman disebut", `illness_name`
    ada di `PRIVATE_CHANGED_FIELDS` (setara sensitifnya sama diagnosis).

    `latest_doctor_visit_date`/`latest_doctor_visit_reason` CUMA 2
    field yang eksplisit diminta requirement ("date/reason") -- nama
    dokter/klinik/diagnosis/catatan kunjungan TIDAK PERNAH disertakan
    di ringkasan operasional ini (requirement: "no diagnosis, severity
    inference, or treatment recommendation").
    """
    latest_temp = TemperatureLog.query.filter(
        TemperatureLog.child_id == child_id,
        TemperatureLog.timestamp >= window_start,
        TemperatureLog.timestamp <= as_of_at,
    ).order_by(TemperatureLog.timestamp.desc(), TemperatureLog.id.desc()).first()

    window_start_date = window_start.date()
    as_of_date = as_of_at.date()
    illness_rows = IllnessLog.query.filter(
        IllnessLog.child_id == child_id,
        IllnessLog.start_date <= as_of_date,
    ).filter(
        (IllnessLog.end_date.is_(None)) | (IllnessLog.end_date >= window_start_date)
    ).order_by(IllnessLog.start_date.desc(), IllnessLog.id.desc()).limit(MAX_ILLNESS_ROWS).all()

    latest_visit = DoctorVisitLog.query.filter(
        DoctorVisitLog.child_id == child_id,
    ).order_by(DoctorVisitLog.visit_date.desc(), DoctorVisitLog.id.desc()).first()

    return {
        "latest_temperature_celsius": latest_temp.temperature_celsius if latest_temp else None,
        "latest_temperature_at": _iso_wib(latest_temp.timestamp) if latest_temp else None,
        "illnesses_overlapping_window": [
            {
                "start_date": ill.start_date.isoformat(),
                "end_date": ill.end_date.isoformat() if ill.end_date else None,
                "is_ongoing": ill.end_date is None,
            }
            for ill in illness_rows
        ],
        "latest_doctor_visit_date": latest_visit.visit_date.isoformat() if latest_visit else None,
        "latest_doctor_visit_reason": latest_visit.reason if latest_visit else None,
    }


def _format_dose(schedule):
    if schedule.dose_value is None or not schedule.dose_unit:
        return None
    return f"{schedule.dose_value:g} {schedule.dose_unit}"


def _medication_section(child_id, window_start, as_of_at):
    """
    REUSE PENUH `utils/medication_schedule_engine.py` -- TIDAK PERNAH
    menghitung ulang status upcoming/due/overdue sendiri. `today`/`now`
    yang dilewatkan ke mesin itu SELALU `as_of_at` (BEKU), TIDAK PERNAH
    `now_wib()` baru -- konsisten "frozen window" requirement.

    Horizon "next due occurrence" DIDOKUMENTASIKAN APA ADANYA (bukan
    angka baru yang dikarang di sini): `next_actionable_occurrence_at`
    CUMA mencari di antara okurensi yang SUDAH dihitung
    `compute_schedule_occurrences` -- yang DIBATASI sampai HARI INI
    (`as_of_at.date()`) SAJA, TIDAK PERNAH okurensi besok/lusa (lihat
    docstring fungsi itu) -- jadi "next occurrence" di sini CUMA bisa
    ketemu kalau MASIH ADA jam pemberian tersisa HARI INI yang belum
    di-resolve. Ini keterbatasan Fase 1 yang didokumentasikan
    (backend/docs/CAREGIVER_HANDOVER.md), BUKAN bug -- reuse APA ADANYA
    dari mesin yang sudah ada, tidak menulis logic horizon baru.
    """
    today = as_of_at.date()
    schedules = MedicationSchedule.query.filter(
        MedicationSchedule.child_id == child_id,
        MedicationSchedule.is_active.is_(True),
    ).order_by(MedicationSchedule.id.asc()).all()

    action_query_start = today - timedelta(days=MEDICATION_LOOKBACK_DAYS)

    administered_in_window = []
    skipped_in_window = []
    overdue = []
    next_candidates = []

    for schedule in schedules:
        actions = MedicationDoseAction.query.filter(
            MedicationDoseAction.schedule_id == schedule.id,
            MedicationDoseAction.occurrence_at >= action_query_start,
        ).all()
        actions_by_occurrence = {a.occurrence_at: a for a in actions}
        occurrences = compute_schedule_occurrences(schedule, actions_by_occurrence, today, as_of_at)

        dose_label = _format_dose(schedule)
        for occ in occurrences:
            entry = {
                "medication_name": schedule.medication_name,
                "dose": dose_label,
                "occurrence_at": _iso_wib(occ["occurrence_at"]),
            }
            if occ["status"] is not None and window_start <= occ["occurrence_at"] <= as_of_at:
                if occ["status"] == "administered":
                    administered_in_window.append(entry)
                elif occ["status"] == "skipped":
                    skipped_in_window.append(entry)
            elif occ["status"] is None and occ["state"] == "overdue":
                overdue.append(entry)

        next_at = next_actionable_occurrence_at(schedule, actions_by_occurrence, today, as_of_at)
        if next_at is not None and next_at > as_of_at:
            next_candidates.append({
                "medication_name": schedule.medication_name,
                "dose": dose_label,
                "occurrence_at": _iso_wib(next_at),
            })

    administered_in_window.sort(key=lambda e: e["occurrence_at"])
    skipped_in_window.sort(key=lambda e: e["occurrence_at"])
    overdue.sort(key=lambda e: e["occurrence_at"])
    next_candidates.sort(key=lambda e: e["occurrence_at"])

    return {
        "administered_in_window": administered_in_window[:MAX_MEDICATION_RESOLVED_ROWS],
        "skipped_in_window": skipped_in_window[:MAX_MEDICATION_RESOLVED_ROWS],
        "overdue_as_of_as_of_at": overdue[:MAX_MEDICATION_OVERDUE_ROWS],
        "next_occurrence": next_candidates[0] if next_candidates else None,
    }


def _reminder_section(child_id, window_start, as_of_at):
    """REUSE PENUH `utils/reminder_engine.py` -- pola SAMA PERSIS `_medication_section` di atas, TIDAK PERNAH menghitung ulang status okurensi sendiri."""
    today = as_of_at.date()
    reminders = Reminder.query.filter(
        Reminder.child_id == child_id,
        Reminder.is_active.is_(True),
    ).order_by(Reminder.id.asc()).all()

    resolved_in_window = []
    overdue = []
    next_candidates = []

    for reminder in reminders:
        lookback_start = today - timedelta(days=REMINDER_LOOKBACK_DAYS)
        actions = ReminderAction.query.filter(
            ReminderAction.reminder_id == reminder.id,
            ReminderAction.occurrence_at >= lookback_start,
        ).all()
        actions_by_date = {a.occurrence_at.date(): a for a in actions}
        occurrences = compute_reminder_occurrences(reminder, actions_by_date, today, as_of_at)

        for occ in occurrences:
            entry = {
                "reminder_type": reminder.reminder_type,
                "title": reminder.title,
                "occurrence_at": _iso_wib(occ["occurrence_at"]),
            }
            if occ["status"] is not None and window_start <= occ["occurrence_at"] <= as_of_at:
                resolved_in_window.append({**entry, "status": occ["status"]})
            elif occ["status"] is None and occ["state"] == "overdue":
                overdue.append(entry)

        next_at = next_pending_occurrence_at(reminder, actions_by_date, today)
        if next_at is not None and next_at > as_of_at:
            next_candidates.append({
                "reminder_type": reminder.reminder_type,
                "title": reminder.title,
                "occurrence_at": _iso_wib(next_at),
            })

    resolved_in_window.sort(key=lambda e: e["occurrence_at"])
    overdue.sort(key=lambda e: e["occurrence_at"])
    next_candidates.sort(key=lambda e: e["occurrence_at"])

    return {
        "resolved_in_window": resolved_in_window[:MAX_REMINDER_RESOLVED_ROWS],
        "overdue_as_of_as_of_at": overdue[:MAX_REMINDER_OVERDUE_ROWS],
        "next_occurrence": next_candidates[0] if next_candidates else None,
    }


def build_caregiver_handover_summary(child, handover, generated_at):
    """
    Bangun ringkasan LENGKAP (dict siap-`jsonify`) buat 1
    `CaregiverHandover` -- SATU-SATUNYA fungsi yang dipanggil route,
    TIDAK PERNAH membaca jam sistem sendiri (`generated_at` WAJIB
    parameter dari pemanggil). Dipanggil ULANG setiap kali handover
    dibaca (GET) — hasilnya TIDAK PERNAH disimpan balik ke
    `CaregiverHandover`, `window_start`/`as_of_at`/`note`/`status`
    dibaca APA ADANYA dari baris `handover` yang sudah ada.
    """
    window_start = handover.window_start
    as_of_at = handover.as_of_at
    return {
        "window_start": _iso_wib(window_start),
        "as_of_at": _iso_wib(as_of_at),
        "timezone": "Asia/Jakarta",
        "generated_at": _iso_wib(generated_at),
        "child_display_name": child.nickname or child.name,
        "creator_display_name": handover.creator.name if handover.creator else None,
        "status": handover.status,
        "disclaimer": DISCLAIMER,
        "privacy_note": PRIVACY_NOTE,
        "feeding": _feeding_section(child.id, window_start, as_of_at),
        "sleep": _sleep_section(child.id, window_start, as_of_at),
        "diaper": _diaper_section(child.id, window_start, as_of_at),
        "pumping": _pumping_section(child.id, window_start, as_of_at),
        "activity_mood": _activity_mood_section(child.id, window_start, as_of_at),
        "health": _health_section(child.id, window_start, as_of_at),
        "medication": _medication_section(child.id, window_start, as_of_at),
        "reminders": _reminder_section(child.id, window_start, as_of_at),
    }
