"""
Doctor Consultation Workflow — Phase 1 (lihat backend/docs/DOCTOR_CONSULTATION.md
buat kontrak lengkapnya).

Mesin MURNI-DATA di sini TIDAK PERNAH mendiagnosis, TIDAK PERNAH ngasih
skor risiko, TIDAK PERNAH bikin kesimpulan klinis apa pun -- cuma
merangkum catatan yang caregiver SENDIRI udah masukin, dalam bentuk
terstruktur, buat dibawa ke dokter. `today`/`now` SELALU parameter dari
pemanggil (route), PERSIS pola utils/insights_engine.py -- modul ini
TIDAK PERNAH manggil jam sistem sendiri.

REUSE, BUKAN DUPLIKASI: metrik per-kategori (feeding/sleep/diaper/
pumping/activity/mood/growth/health/milestones) DAN kartu Smart Insight
(kode + threshold + kebijakan data-parsial) SELURUHNYA dipanggil
langsung dari utils/insights_engine.py -- modul ini CUMA nambahin
deskripsi Indonesia (allowlist TERPISAH, lihat INSIGHT_CODE_DESCRIPTIONS
di bawah -- BUKAN salinan frontend/src/utils/insightCodes.js, itu murni
buat kartu UI interaktif, ini murni buat teks laporan/PDF) dan
orkestrasi rentang tanggal custom yang endpoint /insights sendiri nggak
dukung (endpoint itu cuma preset 7d/30d).

Data-minimization (lihat DEFAULT_INCLUDED_SECTIONS/SENSITIVE_SECTIONS
di bawah): field bebas-teks paling sensitif (`notes` di SEMUA tipe
record) TIDAK PERNAH disertakan di laporan ini, SAMA SEKALI, bahkan di
section yang secara eksplisit dipilih caregiver -- lebih ketat dari
field "sensitif" yang disebutkan (nama obat/dosis/nama
penyakit/gejala/diagnosis/nama dokter/klinik), soalnya `notes` bisa
berisi APA PUN yang caregiver ketik bebas, jauh lebih luas dari
field-field bernama di atas.
"""
from datetime import datetime, time, timedelta

from extensions import db
from models import (
    DoctorVisitLog, GrowthMeasurement, IllnessLog,
    MedicationLog, MilestoneLog, TemperatureLog,
)
from routes.children_routes import _build_vaccination_list
from routes.report_routes import _age_str
from utils.insights_engine import (
    build_comparison,
    build_insights,
    compute_activity_metrics,
    compute_diaper_metrics,
    compute_feeding_metrics,
    compute_growth_metrics,
    compute_health_metrics,
    compute_milestone_metrics,
    compute_mood_metrics,
    compute_pumping_metrics,
    compute_sleep_metrics,
    _measured_total_or_none,
)

# --------------------------------------------------------------------------
# 16 section code -- allowlist TETAP, dipakai validasi request DAN kunci
# dict `sections` di response (preview & PDF SAMA PERSIS, satu sumber
# kebenaran).
# --------------------------------------------------------------------------
SECTION_CHILD_SUMMARY = "child_summary"
SECTION_FEEDING = "feeding"
SECTION_SLEEP = "sleep"
SECTION_DIAPER = "diaper"
SECTION_PUMPING = "pumping"
SECTION_ACTIVITY_MOOD = "activity_mood"
SECTION_GROWTH = "growth"
SECTION_TEMPERATURE = "temperature"
SECTION_ILLNESS = "illness"
SECTION_MEDICATION = "medication"
SECTION_VACCINATION = "vaccination"
SECTION_MILESTONES = "milestones"
SECTION_DOCTOR_VISITS = "doctor_visits"
SECTION_INSIGHTS = "insights"
SECTION_QUESTIONS = "questions"
SECTION_NOTE = "note"

SECTION_CODES = (
    SECTION_CHILD_SUMMARY, SECTION_FEEDING, SECTION_SLEEP, SECTION_DIAPER,
    SECTION_PUMPING, SECTION_ACTIVITY_MOOD, SECTION_GROWTH, SECTION_TEMPERATURE,
    SECTION_ILLNESS, SECTION_MEDICATION, SECTION_VACCINATION, SECTION_MILESTONES,
    SECTION_DOCTOR_VISITS, SECTION_INSIGHTS, SECTION_QUESTIONS, SECTION_NOTE,
)
_SECTION_CODE_SET = frozenset(SECTION_CODES)
MAX_SECTIONS = len(SECTION_CODES)

# Default privacy-conscious -- HANYA kategori struktural/angka/kategori,
# TIDAK ADA yang secara default menyertakan teks bebas ATAUPUN identitas
# medis spesifik anak (nama obat/penyakit/dokter/klinik/diagnosis).
DEFAULT_INCLUDED_SECTIONS = frozenset({
    SECTION_CHILD_SUMMARY, SECTION_FEEDING, SECTION_SLEEP, SECTION_DIAPER,
    SECTION_GROWTH, SECTION_TEMPERATURE, SECTION_VACCINATION, SECTION_MILESTONES,
})

# Section yang butuh opt-in EKSPLISIT DAN mengandung data sensitif
# (identitas medis spesifik anak/provider, ATAU teks bebas caregiver
# sendiri) -- dipakai frontend buat nampilin indikator/peringatan privasi
# sebelum export, dan (questions/note) buat menegakkan can_add_private_notes.
SENSITIVE_SECTIONS = frozenset({
    SECTION_ILLNESS, SECTION_MEDICATION, SECTION_DOCTOR_VISITS, SECTION_QUESTIONS, SECTION_NOTE,
})

# Batas baris per section detail -- SELALU dibatasi + ditandai `truncated`
# kalau ada baris yang nggak ditampilkan (lihat _capped_query_result).
MAX_ILLNESS_ROWS = 15
MAX_MEDICATION_ROWS = 20
MAX_GROWTH_ROWS = 20
MAX_MILESTONE_ROWS = 15
MAX_DOCTOR_VISIT_ROWS = 10

QUESTIONS_MAX_LEN = 1000
NOTE_MAX_LEN = 1000
MAX_RANGE_DAYS = 90

# Batas ukuran body request KHUSUS endpoint konsultasi -- jauh lebih
# ketat dari MAX_CONTENT_LENGTH global aplikasi (6MB, lihat config.py,
# dilonggarkan buat upload foto). Body endpoint ini SEHARUSNYA cuma
# berisi <=16 kode section pendek, metadata periode, dan 2 field teks
# yang sudah dibatasi panjangnya sendiri (QUESTIONS_MAX_LEN/NOTE_MAX_LEN)
# -- 20KB SUDAH sangat longgar buat itu. Dicek SEDINI mungkin (lewat
# `Content-Length`, SEBELUM body di-parse JSON ataupun query database
# apa pun dijalankan) di routes/doctor_consultation_routes.py, biar
# body raksasa nggak nyeret CPU parsing/laporan/render PDF sia-sia.
MAX_CONSULTATION_BODY_BYTES = 20_000

DISCLAIMER = (
    "Laporan ini dibuat dari catatan yang dimasukkan oleh caregiver dan bukan "
    "diagnosis atau pengganti konsultasi medis profesional."
)
PRIVACY_NOTE = (
    "Laporan ini hanya menampilkan bagian yang Anda pilih sendiri. Bagian yang "
    "berisi rincian sensitif (obat, riwayat sakit, kunjungan dokter, pertanyaan, "
    "dan catatan tambahan) hanya disertakan kalau Anda memilihnya secara eksplisit."
)
GENERATED_STATEMENT = "Dibuat dari catatan yang dimasukkan oleh caregiver."

PERIOD_PRESETS = {"7d": 7, "14d": 14, "30d": 30}


class ConsultationValidationError(ValueError):
    """Input periode/section/teks nggak valid -- route menangkap ini, balas 400."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def resolve_consultation_period(period_input, today):
    """
    `period_input`: dict {"preset": "7d"|"14d"|"30d"|"custom",
    "start_date"?, "end_date"?}. Balikin dict {preset, start_date,
    end_date, days} (semua `date`, kecuali preset/days), ATAU raise
    ConsultationValidationError -- backend TETAP otoritatif buat validasi
    rentang, terlepas apa pun yang sudah dicek di frontend.
    """
    if not isinstance(period_input, dict):
        raise ConsultationValidationError("period wajib diisi")

    preset = period_input.get("preset")
    if preset in PERIOD_PRESETS:
        days = PERIOD_PRESETS[preset]
        end_date = today
        start_date = end_date - timedelta(days=days - 1)
        return {"preset": preset, "start_date": start_date, "end_date": end_date, "days": days}

    if preset != "custom":
        raise ConsultationValidationError("period.preset harus salah satu dari: 7d, 14d, 30d, custom")

    start_date = _parse_date_field(period_input.get("start_date"), "start_date")
    end_date = _parse_date_field(period_input.get("end_date"), "end_date")
    if end_date < start_date:
        raise ConsultationValidationError("end_date tidak boleh sebelum start_date")
    if end_date > today:
        raise ConsultationValidationError("end_date tidak boleh di masa depan")
    days = (end_date - start_date).days + 1
    if days > MAX_RANGE_DAYS:
        raise ConsultationValidationError(f"Rentang tanggal maksimal {MAX_RANGE_DAYS} hari")
    return {"preset": "custom", "start_date": start_date, "end_date": end_date, "days": days}


def _parse_date_field(raw, field_name):
    if not raw or not isinstance(raw, str):
        raise ConsultationValidationError(f"{field_name} wajib diisi (format YYYY-MM-DD)")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise ConsultationValidationError(f"{field_name} tidak valid, format harus YYYY-MM-DD")


def validate_sections(section_input):
    """List section tervalidasi (unik, dikenal, urutan diambil dari SECTION_CODES) atau default privacy-conscious kalau `None`."""
    if section_input is None:
        return [c for c in SECTION_CODES if c in DEFAULT_INCLUDED_SECTIONS]
    if not isinstance(section_input, list):
        raise ConsultationValidationError("sections harus berupa list")
    if len(section_input) > MAX_SECTIONS:
        raise ConsultationValidationError("Jumlah section yang dipilih melebihi batas maksimum")

    seen = set()
    for code in section_input:
        if not isinstance(code, str) or code not in _SECTION_CODE_SET:
            raise ConsultationValidationError(f"Section tidak dikenal: {code!r}")
        if code in seen:
            raise ConsultationValidationError(f"Section duplikat: {code!r}")
        seen.add(code)
    # Urutan TETAP (ikut SECTION_CODES), bukan urutan request mentah --
    # respons deterministik & konsisten preview vs PDF.
    return [c for c in SECTION_CODES if c in seen]


def _normalize_free_text(raw, field_name, max_len):
    """
    Normalisasi teks TRANSIEN (questions/additional_note) -- SELALU
    string biasa, TIDAK PERNAH ditafsirkan Markdown/HTML di sini
    (escaping HTML/PDF-markup jadi tanggung jawab pemanggil SAAT
    dirender -- lihat routes/doctor_consultation_routes.py &
    utils/consultation_pdf.py -- modul ini CUMA validasi+normalisasi).
    """
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ConsultationValidationError(f"{field_name} harus berupa teks")
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    if len(normalized) > max_len:
        raise ConsultationValidationError(f"{field_name} maksimal {max_len} karakter")
    return normalized


def validate_questions(raw):
    return _normalize_free_text(raw, "questions", QUESTIONS_MAX_LEN)


def validate_note(raw):
    return _normalize_free_text(raw, "additional_note", NOTE_MAX_LEN)


def _datetime_bounds(start_date, end_date):
    """[start_dt, end_dt_exclusive) WIB naive -- pola sama persis utils/insights_engine.py:_range_bounds (fungsi privat, sengaja nggak diimpor lintas modul)."""
    start_dt = datetime.combine(start_date, time.min)
    end_dt_exclusive = datetime.combine(end_date + timedelta(days=1), time.min)
    return start_dt, end_dt_exclusive


def _age_months_as_of(birth_date, as_of_date):
    """
    Sama persis rumus routes/children_routes.py:_age_in_months, TAPI
    diparameterkan ke `as_of_date` (bukan today_wib() internal) --
    laporan ini butuh usia relatif ke `end_date` periode (yang bisa
    beda dari hari ini kalau rentang custom-nya di masa lalu), bukan
    "sekarang".
    """
    return (as_of_date.year - birth_date.year) * 12 + (as_of_date.month - birth_date.month) - (
        1 if as_of_date.day < birth_date.day else 0
    )


def _capped_query_result(query, cap):
    """(rows dibatasi `cap`, total_count SEBENARNYA, truncated bool) -- 2 query kecil, dua-duanya kena index child_id/tanggal yang udah ada."""
    total_count = query.count()
    rows = query.limit(cap).all()
    return rows, total_count, total_count > cap


# --------------------------------------------------------------------------
# Deskripsi Indonesia buat kode insight -- allowlist EKSPLISIT TERPISAH
# dari frontend/src/utils/insightCodes.js (itu buat kartu UI interaktif,
# ini buat laporan/PDF yang dirender SERVER-SIDE; keduanya harus
# dimutakhirkan manual kalau INSIGHT_ALLOWLIST backend berubah -- lihat
# docstring modul). TIDAK PERNAH klaim medis/diagnosis -- murni deskripsi
# arah+besaran angka.
# --------------------------------------------------------------------------
INSIGHT_CODE_DESCRIPTIONS = {
    "insufficient_data": lambda v: (
        "Data selama periode ini masih terbatas, sehingga perbandingan tren belum dapat ditampilkan."
    ),
    "sleep_duration_increased": lambda v: f"Total durasi tidur tercatat meningkat sekitar {v} menit dibanding periode sebelumnya.",
    "sleep_duration_decreased": lambda v: f"Total durasi tidur tercatat menurun sekitar {v} menit dibanding periode sebelumnya.",
    "feeding_count_increased": lambda v: f"Jumlah sesi menyusui/makan tercatat meningkat {v} kali dibanding periode sebelumnya.",
    "feeding_count_decreased": lambda v: f"Jumlah sesi menyusui/makan tercatat menurun {v} kali dibanding periode sebelumnya.",
    "diaper_count_increased": lambda v: f"Jumlah ganti popok tercatat meningkat {v} kali dibanding periode sebelumnya.",
    "diaper_count_decreased": lambda v: f"Jumlah ganti popok tercatat menurun {v} kali dibanding periode sebelumnya.",
    "pumping_volume_increased": lambda v: f"Volume ASI perah tercatat meningkat sekitar {v} ml dibanding periode sebelumnya.",
    "pumping_volume_decreased": lambda v: f"Volume ASI perah tercatat menurun sekitar {v} ml dibanding periode sebelumnya.",
    "activity_duration_increased": lambda v: f"Durasi aktivitas tercatat meningkat sekitar {v} menit dibanding periode sebelumnya.",
    "activity_duration_decreased": lambda v: f"Durasi aktivitas tercatat menurun sekitar {v} menit dibanding periode sebelumnya.",
    "growth_no_recent_measurement": lambda v: "Belum ada pengukuran pertumbuhan (berat/tinggi/lingkar kepala) dalam waktu yang cukup baru.",
}
_UNKNOWN_INSIGHT_DESCRIPTION = "Ada observasi tambahan dari catatan yang tercatat."


def _describe_insight_card(card):
    describer = INSIGHT_CODE_DESCRIPTIONS.get(card["code"])
    description = describer(card["value"]) if describer else _UNKNOWN_INSIGHT_DESCRIPTION
    return {
        "code": card["code"],
        "description": description,
        "metric": card["metric"],
        "direction": card["direction"],
        "value": card["value"],
    }


# --------------------------------------------------------------------------
# Section builders -- masing-masing balikin dict data-minimal, SELALU
# di-scope ke [start_date, end_date] periode (kecuali vaksinasi, yang
# memang status TERKINI, bukan histori periode).
# --------------------------------------------------------------------------

def _child_summary_section(child, end_date, health_metrics):
    return {
        "display_name": child.nickname or child.name,
        "birth_date": child.birth_date.isoformat(),
        "gender": child.gender,
        "age_as_of_report_end": _age_str(child.birth_date, end_date),
        "medication_event_count_in_period": health_metrics["medication_event_count"],
        "doctor_visit_count_in_period": health_metrics["doctor_visit_count"],
        "illness_record_count_in_period": health_metrics["illness_record_count"],
        "temperature_record_count_in_period": health_metrics["temperature_record_count"],
    }


def _growth_section(child_id, start_date, end_date, today):
    growth_metrics, _ = compute_growth_metrics(child_id, today, start_date, end_date)
    query = (
        GrowthMeasurement.query.filter(
            GrowthMeasurement.child_id == child_id,
            GrowthMeasurement.measured_date >= start_date,
            GrowthMeasurement.measured_date <= end_date,
        ).order_by(GrowthMeasurement.measured_date.asc())
    )
    rows, total_count, truncated = _capped_query_result(query, MAX_GROWTH_ROWS)
    return {
        "latest": growth_metrics["latest"],
        "previous": growth_metrics["previous"],
        "weight_change_kg": growth_metrics["weight_change_kg"],
        "height_change_cm": growth_metrics["height_change_cm"],
        "head_circumference_change_cm": growth_metrics["head_circumference_change_cm"],
        "days_since_latest_measurement": growth_metrics["days_since_latest_measurement"],
        "measurements_in_period": [
            {
                "measured_date": r.measured_date.isoformat(),
                "weight_kg": r.weight_kg,
                "height_cm": r.height_cm,
                "head_circumference_cm": r.head_circumference_cm,
            }
            for r in rows
        ],
        "total_count_in_period": total_count,
        "truncated": truncated,
    }


def _temperature_section(child_id, start_date, end_date, health_metrics):
    start_dt, end_dt = _datetime_bounds(start_date, end_date)
    avg_temp, min_temp, max_temp = db.session.query(
        db.func.avg(TemperatureLog.temperature_celsius),
        db.func.min(TemperatureLog.temperature_celsius),
        db.func.max(TemperatureLog.temperature_celsius),
    ).filter(
        TemperatureLog.child_id == child_id,
        TemperatureLog.timestamp >= start_dt,
        TemperatureLog.timestamp < end_dt,
    ).one()
    return {
        "record_count_in_period": health_metrics["temperature_record_count"],
        "avg_celsius_in_period": round(avg_temp, 1) if avg_temp is not None else None,
        "min_celsius_in_period": min_temp,
        "max_celsius_in_period": max_temp,
        "latest_temperature_celsius": health_metrics["latest_temperature_celsius"],
        "latest_temperature_at": health_metrics["latest_temperature_at"],
    }


def _illness_section(child_id, start_date, end_date):
    query = IllnessLog.query.filter(
        IllnessLog.child_id == child_id,
        IllnessLog.start_date >= start_date,
        IllnessLog.start_date <= end_date,
    ).order_by(IllnessLog.start_date.desc())
    rows, total_count, truncated = _capped_query_result(query, MAX_ILLNESS_ROWS)
    return {
        "entries": [
            {
                "illness_name": r.illness_name,
                "start_date": r.start_date.isoformat(),
                "end_date": r.end_date.isoformat() if r.end_date else None,
                "is_ongoing": r.end_date is None,
                "symptoms": r.symptoms,
            }
            for r in rows
        ],
        "total_count_in_period": total_count,
        "truncated": truncated,
    }


def _medication_section(child_id, start_date, end_date):
    start_dt, end_dt = _datetime_bounds(start_date, end_date)
    query = MedicationLog.query.filter(
        MedicationLog.child_id == child_id,
        MedicationLog.timestamp >= start_dt,
        MedicationLog.timestamp < end_dt,
    ).order_by(MedicationLog.timestamp.desc())
    rows, total_count, truncated = _capped_query_result(query, MAX_MEDICATION_ROWS)
    return {
        "entries": [
            {
                "medication_name": r.medication_name,
                "dosage": r.dosage,
                "timestamp": r.timestamp.isoformat() + "+07:00",
            }
            for r in rows
        ],
        "total_count_in_period": total_count,
        "truncated": truncated,
    }


def _vaccination_section(child, end_date):
    age_months = _age_months_as_of(child.birth_date, end_date)
    return {
        "vaccinations": _build_vaccination_list(child, age_months),
        "age_months_as_of_report_end": age_months,
    }


def _milestones_section(child_id, start_date, end_date):
    query = MilestoneLog.query.filter(
        MilestoneLog.child_id == child_id,
        MilestoneLog.achieved_date >= start_date,
        MilestoneLog.achieved_date <= end_date,
    ).order_by(MilestoneLog.achieved_date.desc())
    rows, total_count, truncated = _capped_query_result(query, MAX_MILESTONE_ROWS)
    return {
        # `custom_label` SENGAJA nggak pernah disertakan -- teks bebas,
        # konsisten sama kebijakan utils/insights_engine.py.
        "entries": [{"milestone_type": r.milestone_type, "achieved_date": r.achieved_date.isoformat()} for r in rows],
        "total_count_in_period": total_count,
        "truncated": truncated,
    }


def _doctor_visits_section(child_id, start_date, end_date):
    query = DoctorVisitLog.query.filter(
        DoctorVisitLog.child_id == child_id,
        DoctorVisitLog.visit_date >= start_date,
        DoctorVisitLog.visit_date <= end_date,
    ).order_by(DoctorVisitLog.visit_date.desc())
    rows, total_count, truncated = _capped_query_result(query, MAX_DOCTOR_VISIT_ROWS)
    return {
        "entries": [
            {
                "visit_date": r.visit_date.isoformat(),
                "doctor_name": r.doctor_name,
                "clinic_name": r.clinic_name,
                "reason": r.reason,
                "diagnosis": r.diagnosis,
                "next_visit_date": r.next_visit_date.isoformat() if r.next_visit_date else None,
            }
            for r in rows
        ],
        "total_count_in_period": total_count,
        "truncated": truncated,
    }


def _insights_section(child_id, start_date, end_date, today):
    """
    REUSE penuh utils/insights_engine.py -- compute_* per kategori +
    build_comparison + build_insights DIPANGGIL LANGSUNG (bukan
    ditulis ulang), cuma diorkestrasi pakai rentang tanggal PERIODE
    KONSULTASI (bukan preset 7d/30d endpoint /insights) -- lihat
    docstring modul.
    """
    days = (end_date - start_date).days + 1
    prev_end_date = start_date - timedelta(days=1)
    prev_start_date = prev_end_date - timedelta(days=days - 1)

    feeding, feeding_dates = compute_feeding_metrics(child_id, start_date, end_date, days)
    sleep, sleep_dates = compute_sleep_metrics(child_id, start_date, end_date, days)
    diaper, diaper_dates = compute_diaper_metrics(child_id, start_date, end_date, days)
    pumping, pumping_dates = compute_pumping_metrics(child_id, start_date, end_date, days)
    activity, activity_dates = compute_activity_metrics(child_id, start_date, end_date, days)
    mood, mood_dates = compute_mood_metrics(child_id, start_date, end_date)
    growth, growth_dates = compute_growth_metrics(child_id, today, start_date, end_date)
    health, health_dates = compute_health_metrics(child_id, start_date, end_date)
    milestones, milestone_dates = compute_milestone_metrics(child_id, start_date, end_date)

    prev_feeding, _ = compute_feeding_metrics(child_id, prev_start_date, prev_end_date, days)
    prev_sleep, _ = compute_sleep_metrics(child_id, prev_start_date, prev_end_date, days)
    prev_diaper, _ = compute_diaper_metrics(child_id, prev_start_date, prev_end_date, days)
    prev_pumping, _ = compute_pumping_metrics(child_id, prev_start_date, prev_end_date, days)
    prev_activity, _ = compute_activity_metrics(child_id, prev_start_date, prev_end_date, days)

    comparisons = {
        "feeding_count": build_comparison(feeding["total_events"], prev_feeding["total_events"]),
        "sleep_duration_minutes": build_comparison(
            sleep["total_completed_minutes"], prev_sleep["total_completed_minutes"]
        ),
        "diaper_count": build_comparison(diaper["total_events"], prev_diaper["total_events"]),
        "pumping_volume_ml": build_comparison(
            _measured_total_or_none(pumping["total_volume_ml"], pumping["session_count"], pumping["events_with_volume"]),
            _measured_total_or_none(
                prev_pumping["total_volume_ml"], prev_pumping["session_count"], prev_pumping["events_with_volume"]
            ),
        ),
        "activity_duration_minutes": build_comparison(
            _measured_total_or_none(
                activity["total_duration_minutes"], activity["session_count"], activity["events_with_duration"]
            ),
            _measured_total_or_none(
                prev_activity["total_duration_minutes"], prev_activity["session_count"], prev_activity["events_with_duration"]
            ),
        ),
    }

    all_dates = (
        feeding_dates | sleep_dates | diaper_dates | pumping_dates | activity_dates | mood_dates
        | growth_dates | health_dates | milestone_dates
    )
    data_quality = {"has_any_data": len(all_dates) > 0, "days_with_records": len(all_dates)}

    metrics = {
        "feeding": feeding, "sleep": sleep, "diaper": diaper, "pumping": pumping,
        "growth": growth, "health": health, "activity": activity, "mood": mood, "milestones": milestones,
    }
    cards = build_insights(metrics, comparisons, data_quality)
    return {"insights": [_describe_insight_card(c) for c in cards], "data_quality": data_quality}


def build_consultation_report(child, period, sections, questions_text, note_text, today, now):
    """
    Bangun 1 payload laporan lengkap (dipakai SAMA PERSIS oleh preview
    JSON maupun PDF -- 1 sumber kebenaran data, cuma beda cara
    render). MURNI BACA -- TIDAK PERNAH db.session.add/commit, TIDAK
    PERNAH menyimpan `questions_text`/`note_text` (cuma dipantulkan
    balik ke response kalau section-nya dipilih).
    """
    start_date, end_date = period["start_date"], period["end_date"]
    sections_set = set(sections)
    data = {}

    health_metrics = None
    if SECTION_CHILD_SUMMARY in sections_set or SECTION_TEMPERATURE in sections_set:
        health_metrics, _ = compute_health_metrics(child.id, start_date, end_date)

    if SECTION_CHILD_SUMMARY in sections_set:
        data[SECTION_CHILD_SUMMARY] = _child_summary_section(child, end_date, health_metrics)
    if SECTION_FEEDING in sections_set:
        data[SECTION_FEEDING], _ = compute_feeding_metrics(child.id, start_date, end_date, period["days"])
    if SECTION_SLEEP in sections_set:
        data[SECTION_SLEEP], _ = compute_sleep_metrics(child.id, start_date, end_date, period["days"])
    if SECTION_DIAPER in sections_set:
        data[SECTION_DIAPER], _ = compute_diaper_metrics(child.id, start_date, end_date, period["days"])
    if SECTION_PUMPING in sections_set:
        data[SECTION_PUMPING], _ = compute_pumping_metrics(child.id, start_date, end_date, period["days"])
    if SECTION_ACTIVITY_MOOD in sections_set:
        activity, _ = compute_activity_metrics(child.id, start_date, end_date, period["days"])
        mood, _ = compute_mood_metrics(child.id, start_date, end_date)
        data[SECTION_ACTIVITY_MOOD] = {"activity": activity, "mood": mood}
    if SECTION_GROWTH in sections_set:
        data[SECTION_GROWTH] = _growth_section(child.id, start_date, end_date, today)
    if SECTION_TEMPERATURE in sections_set:
        data[SECTION_TEMPERATURE] = _temperature_section(child.id, start_date, end_date, health_metrics)
    if SECTION_ILLNESS in sections_set:
        data[SECTION_ILLNESS] = _illness_section(child.id, start_date, end_date)
    if SECTION_MEDICATION in sections_set:
        data[SECTION_MEDICATION] = _medication_section(child.id, start_date, end_date)
    if SECTION_VACCINATION in sections_set:
        data[SECTION_VACCINATION] = _vaccination_section(child, end_date)
    if SECTION_MILESTONES in sections_set:
        data[SECTION_MILESTONES] = _milestones_section(child.id, start_date, end_date)
    if SECTION_DOCTOR_VISITS in sections_set:
        data[SECTION_DOCTOR_VISITS] = _doctor_visits_section(child.id, start_date, end_date)
    if SECTION_INSIGHTS in sections_set:
        data[SECTION_INSIGHTS] = _insights_section(child.id, start_date, end_date, today)
    if SECTION_QUESTIONS in sections_set:
        data[SECTION_QUESTIONS] = {"text": questions_text or ""}
    if SECTION_NOTE in sections_set:
        data[SECTION_NOTE] = {"text": note_text or ""}

    return {
        "child_id": child.id,
        "child_display_name": child.nickname or child.name,
        "period": {
            "preset": period["preset"],
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "timezone": "Asia/Jakarta",
            "days": period["days"],
        },
        "generated_at": now.isoformat() + "+07:00",
        "disclaimer": DISCLAIMER,
        "privacy_note": PRIVACY_NOTE,
        "generated_statement": GENERATED_STATEMENT,
        "included_sections": list(sections),
        "sensitive_sections_included": [c for c in sections if c in SENSITIVE_SECTIONS],
        "sections": data,
    }
