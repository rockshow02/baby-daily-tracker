"""
Smart Insights & Weekly Summary — Phase 1 (lihat backend/docs/INSIGHTS.md
buat kontrak lengkapnya).

Mesin murni-Python + query di sini KHUSUS buat ringkasan periode (7/30
hari) + perbandingan periode + kartu insight rule-based. Ini SENGAJA
BUKAN perluasan `utils/summary_engine.py` (itu buat perbandingan 1 hari
vs acuan IDAI/AAP per usia — domain beda: guideline-per-usia vs
tren-antar-periode) ataupun `routes/stats_routes.py` (itu tren N-hari
buat grafik `/stats`, TANPA perbandingan periode/insight rule-based, dan
SENGAJA menghitung sesi tidur yang masih berjalan seolah berakhir
"sekarang" — kebalikan dari kebijakan modul ini, lihat docstring
`compute_sleep_metrics` di bawah). Reuse yang beneran dipakai dari situ: pola
query rentang tanggal ter-index, dan `utils/timezone_utils.py` buat
SEMUA batas hari (WIB, BUKAN UTC).

PRINSIP UTAMA (ditegakkan di seluruh modul ini):
  - Informasional doang — TIDAK PERNAH mendiagnosis, TIDAK PERNAH klaim
    kepastian medis, TIDAK PERNAH label "normal"/"abnormal"/"berbahaya"/
    "terlambat"/"tidak sehat"/"aman secara medis" di mana pun (termasuk
    di kode insight — lihat INSIGHT_ALLOWLIST).
  - Nilai yang hilang (volume/durasi/pengukuran) TIDAK PERNAH diam-diam
    dianggap nol saat menghitung RATA-RATA — hanya event yang BENERAN
    punya nilai yang masuk hitungan rata-rata; jumlah event yang PUNYA
    nilai selalu diekspos terpisah.
  - Sesi tidur yang belum selesai (`end_time IS NULL`) TIDAK PERNAH
    dianggap berakhir "sekarang" buat total durasi historis — durasi
    session yang belum selesai TIDAK ADA (bukan 0), jadi dikecualikan
    total dan dihitung terpisah sebagai `unfinished_session_count`.
  - Durasi tidur negatif (data korup/tidak valid — `end_time` sebelum
    `start_time`) ditangani DEFENSIF: sesi itu dikecualikan total dari
    agregat (bukan bikin exception, bukan bikin total negatif).
  - Semua nilai server tetap NUMERIK & TIDAK diformat (pemformatan buat
    manusia ada di frontend) — rounding di sini CUMA buat presisi
    (rata-rata & persentase dibulatkan 1 desimal; total/count tetap
    integer apa adanya — lihat `_round1`).
  - `data_quality.has_any_data`/`days_with_records` memperhitungkan
    SEMUA kategori record yang didukung Smart Insights (feeding, sleep,
    diaper, pumping, activity, mood, growth, temperature, medication,
    doctor visit, illness, milestone) — BUKAN cuma 6 kategori "harian"
    (bug review pasca-Phase-1: anak yang catatannya CUMA growth/health/
    milestone di periode ini sebelumnya salah dianggap "belum ada data
    sama sekali"). Metrik "terakhir tercatat" yang TIDAK di-scope
    periode (growth/temperature/milestone terbaru) TETAP TIDAK PERNAH
    ikut menentukan has_any_data HANYA karena statusnya "terbaru" — ada
    query TERPISAH yang KHUSUS mengecek kejadian di DALAM periode untuk
    keperluan ini (lihat `compute_growth_metrics`/`compute_health_metrics`/
    `compute_milestone_metrics`).
  - Perbandingan periode (`comparisons.feeding_volume_ml`/
    `pumping_volume_ml`/`activity_duration_minutes`) membedakan "nggak
    ada event sama sekali" dan "ada event tapi TIDAK SATU PUN punya
    nilai terukur" dari "beneran ketercatat nol" — kedua kasus pertama
    bikin sisi periode itu `null` di comparisons (BUKAN 0), biar nggak
    ada penurunan/kenaikan palsu 100% yang keluar cuma karena caregiver
    belum sempat isi volume/durasi (bug review pasca-Phase-1). Lihat
    `_measured_total_or_none`/`build_comparison`.
"""
from datetime import datetime, time, timedelta

from models import (
    ActivityLog, DiaperLog, DoctorVisitLog, FeedingLog, GrowthMeasurement,
    IllnessLog, MedicationLog, MilestoneLog, MoodLog, PumpingLog, SleepLog,
    TemperatureLog,
)

# --------------------------------------------------------------------------
# Periode yang didukung
# --------------------------------------------------------------------------

SUPPORTED_PERIODS = {"7d": 7, "30d": 30}
DEFAULT_PERIOD_KEY = "7d"

FEED_TYPES = ("asi_langsung", "asi_perah", "sufor", "mpasi")
MOOD_CATEGORIES = ("ceria", "baik", "sedih", "menangis")

# Ambang tiap rule insight — HEURISTIK PRODUK (dipilih biar kartu nggak
# berisik buat variasi kecil yang wajar hari ke hari), BUKAN ambang
# klinis/medis. Lihat backend/docs/INSIGHTS.md#rule-thresholds buat
# alasan tiap angka.
SLEEP_DURATION_THRESHOLD_MINUTES = 30
FEEDING_COUNT_THRESHOLD = 3
DIAPER_COUNT_THRESHOLD = 3
PUMPING_VOLUME_THRESHOLD_ML = 100
ACTIVITY_DURATION_THRESHOLD_MINUTES = 30
GROWTH_STALE_DAYS = 30

MAX_INSIGHT_CARDS = 5

# Allowlist KETAT kode insight — SATU-SATUNYA kode yang boleh keluar dari
# build_insights(). Frontend WAJIB fallback generik buat kode di luar ini
# (lihat frontend/src/utils/insightCodes.js) — daftar ini SENGAJA
# didokumentasikan ulang di sana biar dua sisi selalu sinkron.
INSIGHT_ALLOWLIST = frozenset({
    "insufficient_data",
    "sleep_duration_increased",
    "sleep_duration_decreased",
    "feeding_count_increased",
    "feeding_count_decreased",
    "diaper_count_increased",
    "diaper_count_decreased",
    "pumping_volume_increased",
    "pumping_volume_decreased",
    "activity_duration_increased",
    "activity_duration_decreased",
    "growth_no_recent_measurement",
})


def _round1(value):
    """Bulatkan 1 desimal — kebijakan rounding TUNGGAL dipakai di semua rata-rata/persentase di modul ini."""
    return round(value, 1)


def resolve_period(period_key, today):
    """
    Balikin dict batas periode SEKARANG + periode SEBELUMNYA yang setara
    panjangnya, semua dalam tanggal WIB lokal (bukan UTC) — `today` WAJIB
    hasil `today_wib()` si pemanggil (route), TIDAK PERNAH dihitung
    ulang di sini, biar seluruh modul ini murni/gampang dites pakai
    tanggal palsu (lihat backend/tests/test_insights.py).

    "7 hari terakhir termasuk hari ini": end_date = today, start_date =
    today - 6 hari (7 hari inklusif). Periode sebelumnya = 7 hari PERSIS
    sebelum start_date (BUKAN overlap), jadi "minggu ini" vs "minggu
    lalu" nggak pernah tumpang tindih walau 1 hari.
    """
    days = SUPPORTED_PERIODS[period_key]
    end_date = today
    start_date = end_date - timedelta(days=days - 1)
    prev_end_date = start_date - timedelta(days=1)
    prev_start_date = prev_end_date - timedelta(days=days - 1)
    return {
        "key": period_key,
        "days": days,
        "start_date": start_date,
        "end_date": end_date,
        "prev_start_date": prev_start_date,
        "prev_end_date": prev_end_date,
    }


def _range_bounds(start_date, end_date):
    """
    [start_dt, end_dt_exclusive) — batas HALF-OPEN, dihitung dari
    tanggal WIB lokal (kolom timestamp di DB SUDAH wall-clock WIB naive,
    lihat utils/timezone_utils.py) — bukan dikonversi dari/ke UTC sama
    sekali, jadi nggak ada risiko catatan WIB kepotong salah tanggal.
    end_dt_exclusive = tengah malam PERSIS hari setelah end_date, biar
    catatan PERSIS di ujung batas (00:00:00.000000 start_date, atau
    23:59:59.999999 end_date) selalu tertangani benar tanpa perlu
    `datetime.max` yang presisinya gampang meleset.
    """
    start_dt = datetime.combine(start_date, time.min)
    end_dt_exclusive = datetime.combine(end_date + timedelta(days=1), time.min)
    return start_dt, end_dt_exclusive


def _empty_daily_trend(start_date, days):
    return {(start_date + timedelta(days=i)).isoformat(): 0 for i in range(days)}


def _trend_dict_to_list(trend, value_key):
    return [
        {"date": d, value_key: (round(v, 1) if isinstance(v, float) else v)}
        for d, v in sorted(trend.items())
    ]


# --------------------------------------------------------------------------
# Feeding
# --------------------------------------------------------------------------

def compute_feeding_metrics(child_id, start_date, end_date, days):
    start_dt, end_dt = _range_bounds(start_date, end_date)
    rows = FeedingLog.query.filter(
        FeedingLog.child_id == child_id,
        FeedingLog.timestamp >= start_dt,
        FeedingLog.timestamp < end_dt,
    ).all()

    total = len(rows)
    by_type = {t: 0 for t in FEED_TYPES}
    volumes = []
    trend = _empty_daily_trend(start_date, days)
    dates = set()

    for r in rows:
        if r.feed_type in by_type:
            by_type[r.feed_type] += 1
        if r.volume_ml is not None:
            volumes.append(r.volume_ml)
        key = r.timestamp.date().isoformat()
        dates.add(key)
        if key in trend:
            trend[key] += 1

    total_volume = sum(volumes)
    events_with_volume = len(volumes)
    avg_volume = _round1(total_volume / events_with_volume) if events_with_volume else None

    metrics = {
        "total_events": total,
        "avg_events_per_day": _round1(total / days),
        "by_type": by_type,
        "total_volume_ml": total_volume,
        "events_with_volume": events_with_volume,
        "avg_volume_ml_per_event": avg_volume,
        "daily_trend": _trend_dict_to_list(trend, "count"),
    }
    return metrics, dates


# --------------------------------------------------------------------------
# Sleep
# --------------------------------------------------------------------------

def compute_sleep_metrics(child_id, start_date, end_date, days):
    """
    Sesi dianggap "milik" periode ini berdasarkan `start_time`-nya
    (BUKAN clipping lintas tengah malam kayak /stats atau /daily-summary
    — itu presisi per-hari yang penting buat grafik HARIAN, tapi buat
    agregat TOTAL 7/30 hari perbedaannya nggak signifikan dan nambah
    kompleksitas tanpa perlu; lihat backend/docs/INSIGHTS.md buat
    perbandingan eksplisit sama /stats).

    Sesi yang MASIH BERJALAN (`end_time is None`) TIDAK PERNAH dianggap
    berakhir "sekarang" — durasinya TIDAK ADA, jadi TIDAK PERNAH masuk
    total/rata-rata, cuma dihitung di `unfinished_session_count`.
    Durasi negatif (data korup) DIKECUALIKAN TOTAL secara defensif.
    """
    start_dt, end_dt = _range_bounds(start_date, end_date)
    rows = SleepLog.query.filter(
        SleepLog.child_id == child_id,
        SleepLog.start_time >= start_dt,
        SleepLog.start_time < end_dt,
    ).all()

    trend = _empty_daily_trend(start_date, days)
    dates = set()
    completed_count = 0
    unfinished_count = 0
    total_minutes = 0.0

    for r in rows:
        key = r.start_time.date().isoformat()
        dates.add(key)
        if r.end_time is None:
            unfinished_count += 1
            continue
        minutes = (r.end_time - r.start_time).total_seconds() / 60
        if minutes < 0:
            # data tidak valid (end_time < start_time) — dikecualikan
            # total, BUKAN dihitung sebagai 0 ataupun bikin total negatif
            continue
        completed_count += 1
        total_minutes += minutes
        if key in trend:
            trend[key] += minutes

    avg_duration = _round1(total_minutes / completed_count) if completed_count else None

    metrics = {
        "completed_session_count": completed_count,
        "unfinished_session_count": unfinished_count,
        "total_completed_minutes": _round1(total_minutes),
        "avg_duration_minutes_per_session": avg_duration,
        "avg_minutes_per_day": _round1(total_minutes / days),
        "daily_trend": _trend_dict_to_list(trend, "total_minutes"),
    }
    return metrics, dates


# --------------------------------------------------------------------------
# Diaper
# --------------------------------------------------------------------------

def compute_diaper_metrics(child_id, start_date, end_date, days):
    """
    `pipis_count`/`bab_count` INKLUSIF terhadap `diaper_type='keduanya'`
    (satu ganti popok keduanya sekaligus ikut kehitung di DUA-duanya) —
    KONSISTEN sama konvensi yang SUDAH ada di routes/stats_routes.py dan
    routes/daily_log_routes.py:daily_summary(), bukan kebijakan baru.
    `combined_count` nyertain hitungan 'keduanya' SENDIRI biar tetap
    bisa dibedain dari pipis-doang/bab-doang. Kategori diambil APA
    ADANYA dari model (`pipis`/`pup`/`keduanya`) — TIDAK ADA kategori
    "lain-lain" yang dikarang.
    """
    start_dt, end_dt = _range_bounds(start_date, end_date)
    rows = DiaperLog.query.filter(
        DiaperLog.child_id == child_id,
        DiaperLog.timestamp >= start_dt,
        DiaperLog.timestamp < end_dt,
    ).all()

    trend = _empty_daily_trend(start_date, days)
    dates = set()
    pipis = 0
    bab = 0
    combined = 0

    for r in rows:
        if r.diaper_type in ("pipis", "keduanya"):
            pipis += 1
        if r.diaper_type in ("pup", "keduanya"):
            bab += 1
        if r.diaper_type == "keduanya":
            combined += 1
        key = r.timestamp.date().isoformat()
        dates.add(key)
        if key in trend:
            trend[key] += 1

    total = len(rows)
    metrics = {
        "total_events": total,
        "pipis_count": pipis,
        "bab_count": bab,
        "combined_count": combined,
        "avg_events_per_day": _round1(total / days),
        "daily_trend": _trend_dict_to_list(trend, "count"),
    }
    return metrics, dates


# --------------------------------------------------------------------------
# Pumping
# --------------------------------------------------------------------------

def compute_pumping_metrics(child_id, start_date, end_date, days):
    start_dt, end_dt = _range_bounds(start_date, end_date)
    rows = PumpingLog.query.filter(
        PumpingLog.child_id == child_id,
        PumpingLog.timestamp >= start_dt,
        PumpingLog.timestamp < end_dt,
    ).all()

    trend_count = _empty_daily_trend(start_date, days)
    trend_volume = _empty_daily_trend(start_date, days)
    dates = set()
    volumes = []
    durations = []

    for r in rows:
        key = r.timestamp.date().isoformat()
        dates.add(key)
        if key in trend_count:
            trend_count[key] += 1
        if r.volume_ml is not None:
            volumes.append(r.volume_ml)
            if key in trend_volume:
                trend_volume[key] += r.volume_ml
        if r.duration_minutes is not None:
            durations.append(r.duration_minutes)

    total_volume = sum(volumes)
    events_with_volume = len(volumes)
    avg_volume = _round1(total_volume / events_with_volume) if events_with_volume else None
    total_duration = sum(durations)

    daily_trend = [
        {"date": d, "count": trend_count[d], "volume_ml": trend_volume[d]}
        for d in sorted(trend_count.keys())
    ]

    metrics = {
        "session_count": len(rows),
        "total_volume_ml": total_volume,
        "events_with_volume": events_with_volume,
        "avg_volume_ml_per_event": avg_volume,
        "total_duration_minutes": total_duration,
        "events_with_duration": len(durations),
        "daily_trend": daily_trend,
    }
    return metrics, dates


# --------------------------------------------------------------------------
# Growth — TIDAK di-scope ke periode (pengukuran jarang, "2 terakhir
# beneran ada" lebih berguna daripada "2 terakhir DALAM 7 hari" yang
# hampir selalu kosong) — query dibatasi `limit(2)`, efisien walau
# riwayat pengukurannya panjang.
# --------------------------------------------------------------------------

def compute_growth_metrics(child_id, today, start_date, end_date):
    """
    `latest`/`previous` TETAP lifetime (BUKAN di-scope periode — lihat
    komentar di atas modul ini soal kenapa), TAPI dates yang dibalikin
    (elemen ke-2 tuple) KHUSUS pengukuran yang measured_date-nya BENERAN
    jatuh di [start_date, end_date] periode ini — query TERPISAH dari
    "2 terakhir" di atas, biar pengukuran lama yang kebetulan jadi
    "terbaru" TIDAK PERNAH keitung sebagai aktivitas periode ini
    (requirement #3 review: jangan anggap record lifetime-only sebagai
    aktivitas periode sekarang cuma gara-gara dia "terbaru").
    """
    measurements = (
        GrowthMeasurement.query.filter_by(child_id=child_id)
        .order_by(GrowthMeasurement.measured_date.desc())
        .limit(2)
        .all()
    )
    latest = measurements[0] if measurements else None
    previous = measurements[1] if len(measurements) > 1 else None

    def _entry(m):
        if not m:
            return None
        return {
            "measured_date": m.measured_date.isoformat(),
            "weight_kg": m.weight_kg,
            "height_cm": m.height_cm,
            "head_circumference_cm": m.head_circumference_cm,
        }

    def _delta(field):
        # TIDAK PERNAH menyimpulkan perubahan kalau SALAH SATU nilai
        # pembandingnya hilang (mis. pengukuran lama cuma isi berat,
        # nggak isi tinggi) — null, bukan nebak/anggap 0.
        if not latest or not previous:
            return None
        a, b = getattr(latest, field), getattr(previous, field)
        if a is None or b is None:
            return None
        return round(a - b, 2)

    period_rows = GrowthMeasurement.query.filter(
        GrowthMeasurement.child_id == child_id,
        GrowthMeasurement.measured_date >= start_date,
        GrowthMeasurement.measured_date <= end_date,
    ).all()
    dates = {m.measured_date.isoformat() for m in period_rows}

    metrics = {
        "latest": _entry(latest),
        "previous": _entry(previous),
        "weight_change_kg": _delta("weight_kg"),
        "height_change_cm": _delta("height_cm"),
        "head_circumference_change_cm": _delta("head_circumference_cm"),
        "days_since_latest_measurement": (today - latest.measured_date).days if latest else None,
    }
    return metrics, dates


# --------------------------------------------------------------------------
# Health overview — PRIVACY-MINIMAL: cuma count + 1 angka suhu terakhir.
# TIDAK PERNAH nyertain notes/symptoms/diagnosis/nama obat/dosis/nama
# dokter/klinik di mana pun di modul ini.
# --------------------------------------------------------------------------

def compute_health_metrics(child_id, start_date, end_date):
    """
    Balikin `(metrics, dates)` — `dates` KHUSUS kejadian yang BENERAN
    jatuh di periode ini (dipakai `data_quality.has_any_data`/
    `days_with_records`), TERPISAH dari `latest_temperature_*` yang
    SENGAJA lifetime (bukan di-scope periode — lihat komentar di
    fungsinya). Query diubah dari `.count()` jadi `.all()` biar count
    DAN tanggalnya didapat dari 1 query yang sama (bukan query
    tambahan) — jumlah query total ke database TIDAK bertambah.
    """
    start_dt, end_dt = _range_bounds(start_date, end_date)
    dates = set()

    temp_rows = TemperatureLog.query.filter(
        TemperatureLog.child_id == child_id,
        TemperatureLog.timestamp >= start_dt,
        TemperatureLog.timestamp < end_dt,
    ).all()
    for r in temp_rows:
        dates.add(r.timestamp.date().isoformat())

    # Suhu TERAKHIR TERCATAT (bukan di-scope periode) — lebih informatif
    # daripada "terakhir DALAM periode" yang sering kosong; mirror pola
    # "pengukuran pertumbuhan terakhir" di atas. TIDAK PERNAH ikut nambah
    # ke `dates` di atas — itu KHUSUS kejadian di dalam periode ini.
    latest_temp = (
        TemperatureLog.query.filter_by(child_id=child_id)
        .order_by(TemperatureLog.timestamp.desc())
        .first()
    )

    med_rows = MedicationLog.query.filter(
        MedicationLog.child_id == child_id,
        MedicationLog.timestamp >= start_dt,
        MedicationLog.timestamp < end_dt,
    ).all()
    for r in med_rows:
        dates.add(r.timestamp.date().isoformat())

    visit_rows = DoctorVisitLog.query.filter(
        DoctorVisitLog.child_id == child_id,
        DoctorVisitLog.visit_date >= start_date,
        DoctorVisitLog.visit_date <= end_date,
    ).all()
    for r in visit_rows:
        dates.add(r.visit_date.isoformat())

    illness_rows = IllnessLog.query.filter(
        IllnessLog.child_id == child_id,
        IllnessLog.start_date >= start_date,
        IllnessLog.start_date <= end_date,
    ).all()
    for r in illness_rows:
        dates.add(r.start_date.isoformat())

    metrics = {
        "temperature_record_count": len(temp_rows),
        "latest_temperature_celsius": latest_temp.temperature_celsius if latest_temp else None,
        "latest_temperature_at": (
            (latest_temp.timestamp.isoformat() + "+07:00") if latest_temp else None
        ),
        "medication_event_count": len(med_rows),
        "doctor_visit_count": len(visit_rows),
        "illness_record_count": len(illness_rows),
    }
    return metrics, dates


# --------------------------------------------------------------------------
# Activity / mood / milestones
# --------------------------------------------------------------------------

def compute_activity_metrics(child_id, start_date, end_date, days):
    start_dt, end_dt = _range_bounds(start_date, end_date)
    rows = ActivityLog.query.filter(
        ActivityLog.child_id == child_id,
        ActivityLog.timestamp >= start_dt,
        ActivityLog.timestamp < end_dt,
    ).all()

    trend = _empty_daily_trend(start_date, days)
    dates = set()
    durations = []
    for r in rows:
        key = r.timestamp.date().isoformat()
        dates.add(key)
        if key in trend:
            trend[key] += 1
        if r.duration_minutes is not None:
            durations.append(r.duration_minutes)

    metrics = {
        "session_count": len(rows),
        "total_duration_minutes": sum(durations),
        "events_with_duration": len(durations),
        "daily_trend": _trend_dict_to_list(trend, "count"),
    }
    return metrics, dates


def compute_mood_metrics(child_id, start_date, end_date):
    start_dt, end_dt = _range_bounds(start_date, end_date)
    rows = MoodLog.query.filter(
        MoodLog.child_id == child_id,
        MoodLog.timestamp >= start_dt,
        MoodLog.timestamp < end_dt,
    ).all()

    counts = {m: 0 for m in MOOD_CATEGORIES}
    dates = set()
    for r in rows:
        dates.add(r.timestamp.date().isoformat())
        if r.mood in counts:
            counts[r.mood] += 1

    metrics = {"counts": counts, "total_events": len(rows)}
    return metrics, dates


def compute_milestone_metrics(child_id, start_date, end_date):
    """Balikin `(metrics, dates)` — sama polanya kayak compute_health_metrics di atas."""
    period_rows = MilestoneLog.query.filter(
        MilestoneLog.child_id == child_id,
        MilestoneLog.achieved_date >= start_date,
        MilestoneLog.achieved_date <= end_date,
    ).all()
    dates = {m.achieved_date.isoformat() for m in period_rows}

    # Milestone TERAKHIR TERCATAT (bukan di-scope periode, sama alasan
    # kayak growth/temperature di atas) — CUMA `milestone_type` +
    # tanggal, TIDAK PERNAH `custom_label` (bisa berisi teks bebas apa
    # pun yang orang tua ketik sendiri). TIDAK PERNAH ikut nambah ke
    # `dates` di atas kalau achieved_date-nya di luar periode ini.
    latest = (
        MilestoneLog.query.filter_by(child_id=child_id)
        .order_by(MilestoneLog.achieved_date.desc())
        .first()
    )

    metrics = {
        "count_in_period": len(period_rows),
        "latest_milestone_type": latest.milestone_type if latest else None,
        "latest_milestone_date": latest.achieved_date.isoformat() if latest else None,
    }
    return metrics, dates


# --------------------------------------------------------------------------
# Perbandingan periode — current vs previous, buat metrik numerik yang
# "reliable" (event count/total sum, BUKAN rata-rata ataupun nilai yang
# sebagian datanya hilang, sesuai instruksi produk).
# --------------------------------------------------------------------------

def _measured_total_or_none(total, event_count, events_with_measured_value):
    """
    Buat metrik "total opsional" (volume/durasi yang nggak semua event
    pasti punya nilainya — feeding/pumping volume, activity duration).
    Membedakan 3 keadaan (requirement review #2 — "distinguish among:
    no events / events exist but none measured / partially measured"):

      1. `event_count == 0` (nggak ada event SAMA SEKALI di periode
         itu) -> `total` dikembalikan APA ADANYA, yaitu 0 — ini
         KETERCATAT NOL YANG BENERAN VALID (persis kayak feeding_count/
         diaper_count=0 dipercaya penuh sebagai "nggak ada event"),
         BUKAN data yang hilang. Nilai 0 di sini SAH dipakai buat
         perbandingan "naik dari 0" (konsisten sama kebijakan
         feeding_count/diaper_count yang sudah ada — previous=0 TETAP
         bikin `change` valid, cuma `percent_change`-nya yang null,
         lihat `build_comparison`).
      2. `event_count > 0` TAPI `events_with_measured_value == 0` (ADA
         event, tapi TIDAK SATU PUN punya nilai tercatat — mis.
         caregiver nyatet sesi pumping tapi lupa isi volume) -> `None`.
         Ini yang BEDA dari kasus 1: kita GENUINELY nggak tau berapa
         totalnya, jadi TIDAK PERNAH dianggap 0 (yang bakal keliru
         diartiin "beneran nggak ada" pas dibandingin — inilah akar
         bug review: total 0 dari `sum([])` kepakai seolah "beneran
         nol" padahal cuma "belum sempat diisi").
      3. `events_with_measured_value > 0` (SEBAGIAN atau SEMUA event
         punya nilai) -> `total` (jumlah dari yang BENERAN terukur)
         dikembalikan apa adanya — kebijakan KONSERVATIF: data parsial
         yang nyata tetap lebih berguna daripada di-null-kan semua
         cuma gara-gara ada 1 event yang bolong.

    Nilai literal 0 yang BENERAN tercatat di 1 event (mis. volume_ml=0)
    SUDAH bikin `events_with_measured_value >= 1` (lihat
    compute_feeding_metrics/compute_pumping_metrics/
    compute_activity_metrics: `volume_ml is not None`/`duration_minutes
    is not None` menghitung 0 literal sebagai "punya nilai") — jadi
    kasus itu otomatis masuk poin 3 di atas, TIDAK PERNAH disamakan
    sama poin 2. Lihat backend/docs/INSIGHTS.md bagian "Kebijakan nilai
    yang hilang" buat detail lengkapnya.
    """
    if event_count > 0 and events_with_measured_value == 0:
        return None
    return total


def build_comparison(current, previous):
    """
    Aturan (didokumentasikan juga di backend/docs/INSIGHTS.md):
      1. Nggak pernah bagi dengan nol.
      2. `previous == 0` -> percent_change = null (BUKAN 100%/None-as-0),
         berlaku SAMA baik current-nya 0 ATAUPUN positif.
      3. Nilai yang hilang TIDAK PERNAH direpresentasikan sebagai
         "penurunan 100%" — buat metrik count-based (feeding_count,
         diaper_count, dst.) current/previous di sini SELALU angka asli
         (0 kalau genuinely nggak ada event). Buat metrik "total
         opsional" (feeding_volume_ml/pumping_volume_ml/
         activity_duration_minutes), pemanggil BOLEH ngirim `None`
         lewat `_measured_total_or_none()` kalau periode itu nggak
         punya SATU PUN event dengan nilai terukur — kalau salah satu
         (atau kedua) sisi `None`, `change`/`percent_change` SAMA-SAMA
         `None` (nggak pernah dihitung dari angka yang sebagian
         "ngarang"), TIDAK PERNAH crash.
      4. change/percent_change dibulatkan 1 desimal (`_round1`), current/
         previous dikembalikan APA ADANYA (integer/float asli ATAU
         `None`, TIDAK diformat).
    """
    if current is None or previous is None:
        return {"current": current, "previous": previous, "change": None, "percent_change": None}
    change = current - previous
    if previous == 0:
        percent_change = None
    else:
        percent_change = _round1((current - previous) / previous * 100)
    return {
        "current": current,
        "previous": previous,
        "change": _round1(change) if isinstance(change, float) else change,
        "percent_change": percent_change,
    }


# --------------------------------------------------------------------------
# Insight rule-based — deterministik, non-medis, allowlist ketat.
# --------------------------------------------------------------------------

def _card(code, metric, direction, value):
    assert code in INSIGHT_ALLOWLIST, f"kode insight di luar allowlist: {code}"
    return {"code": code, "severity": "info", "metric": metric, "direction": direction, "value": value}


def build_insights(metrics, comparisons, data_quality):
    """
    Daftar kartu insight PENDEK, TERURUT DETERMINISTIK (urutan rule
    tetap: tidur -> menyusui -> popok -> pumping -> aktivitas -> tumbuh
    kembang), dibatasi maksimal `MAX_INSIGHT_CARDS`. Kalau periode
    SEKARANG genuinely nggak punya data sama sekali, balikin CUMA
    `insufficient_data` (requirement #8/#9 — nggak ada insight lain yang
    dipaksakan dari data kosong).

    Setiap rule "menurun" SENGAJA disyaratkan periode SEBELUMNYA juga
    punya data (`previous > 0`) — kalau nggak, "penurunan" itu cuma
    artefak "belum pernah dicatat sebelumnya", BUKAN tren beneran
    (requirement #20: no false decrease dari data yang hilang). Rule
    "meningkat" TETAP boleh nyala walau previous=0 (naik dari 0 ke
    sesuatu itu observasi valid, bukan artefak data hilang).
    """
    if not data_quality["has_any_data"]:
        return [_card("insufficient_data", None, None, None)]

    candidates = []

    sleep_cmp = comparisons["sleep_duration_minutes"]
    if metrics["sleep"]["completed_session_count"] > 0:
        delta = sleep_cmp["change"]
        if delta >= SLEEP_DURATION_THRESHOLD_MINUTES:
            candidates.append(_card("sleep_duration_increased", "sleep_duration_minutes", "up", round(delta)))
        elif delta <= -SLEEP_DURATION_THRESHOLD_MINUTES and sleep_cmp["previous"] > 0:
            candidates.append(_card("sleep_duration_decreased", "sleep_duration_minutes", "down", round(abs(delta))))

    feeding_cmp = comparisons["feeding_count"]
    if metrics["feeding"]["total_events"] > 0:
        delta = feeding_cmp["change"]
        if delta >= FEEDING_COUNT_THRESHOLD:
            candidates.append(_card("feeding_count_increased", "feeding_count", "up", delta))
        elif delta <= -FEEDING_COUNT_THRESHOLD and feeding_cmp["previous"] > 0:
            candidates.append(_card("feeding_count_decreased", "feeding_count", "down", abs(delta)))

    diaper_cmp = comparisons["diaper_count"]
    if metrics["diaper"]["total_events"] > 0:
        delta = diaper_cmp["change"]
        if delta >= DIAPER_COUNT_THRESHOLD:
            candidates.append(_card("diaper_count_increased", "diaper_count", "up", delta))
        elif delta <= -DIAPER_COUNT_THRESHOLD and diaper_cmp["previous"] > 0:
            candidates.append(_card("diaper_count_decreased", "diaper_count", "down", abs(delta)))

    # pumping_volume_ml/activity_duration_minutes BISA `None` di kedua
    # sisi (lihat _measured_total_or_none) kalau periode itu nggak
    # punya SATU PUN event dengan nilai terukur — `delta is not None`
    # jadi gate WAJIB di sini (bukan cuma penghias): tanpa ini,
    # `delta >= AMBANG` bakal TypeError begitu salah satu sisi `None`
    # (mis. periode sekarang keukur tapi periode sebelumnya nggak sama
    # sekali). Kartu kenaikan/penurunan CUMA digenerate kalau KEDUA
    # periode punya nilai terukur beneran (requirement review #2).
    pumping_cmp = comparisons["pumping_volume_ml"]
    delta = pumping_cmp["change"]
    if delta is not None:
        if delta >= PUMPING_VOLUME_THRESHOLD_ML:
            candidates.append(_card("pumping_volume_increased", "pumping_volume_ml", "up", delta))
        elif delta <= -PUMPING_VOLUME_THRESHOLD_ML and pumping_cmp["previous"] > 0:
            candidates.append(_card("pumping_volume_decreased", "pumping_volume_ml", "down", abs(delta)))

    activity_cmp = comparisons["activity_duration_minutes"]
    delta = activity_cmp["change"]
    if delta is not None:
        if delta >= ACTIVITY_DURATION_THRESHOLD_MINUTES:
            candidates.append(_card("activity_duration_increased", "activity_duration_minutes", "up", delta))
        elif delta <= -ACTIVITY_DURATION_THRESHOLD_MINUTES and activity_cmp["previous"] > 0:
            candidates.append(_card("activity_duration_decreased", "activity_duration_minutes", "down", abs(delta)))

    growth = metrics["growth"]
    stale = growth["days_since_latest_measurement"]
    if stale is None or stale > GROWTH_STALE_DAYS:
        candidates.append(_card("growth_no_recent_measurement", "growth", None, None))

    return candidates[:MAX_INSIGHT_CARDS]


# --------------------------------------------------------------------------
# Orkestrasi 1 response lengkap
# --------------------------------------------------------------------------

def build_insight_response(child_id, period_key, today):
    """
    Bangun payload lengkap `/children/<id>/insights` — SATU-SATUNYA
    fungsi yang perlu dipanggil route (lihat routes/insights_routes.py).
    Fungsi ini murni baca (TIDAK PERNAH db.session.add/commit) — melihat
    insight TIDAK PERNAH mengubah data anak.
    """
    period = resolve_period(period_key, today)
    days = period["days"]

    feeding, feeding_dates = compute_feeding_metrics(child_id, period["start_date"], period["end_date"], days)
    sleep, sleep_dates = compute_sleep_metrics(child_id, period["start_date"], period["end_date"], days)
    diaper, diaper_dates = compute_diaper_metrics(child_id, period["start_date"], period["end_date"], days)
    pumping, pumping_dates = compute_pumping_metrics(child_id, period["start_date"], period["end_date"], days)
    activity, activity_dates = compute_activity_metrics(child_id, period["start_date"], period["end_date"], days)
    mood, mood_dates = compute_mood_metrics(child_id, period["start_date"], period["end_date"])
    growth, growth_dates = compute_growth_metrics(child_id, today, period["start_date"], period["end_date"])
    health, health_dates = compute_health_metrics(child_id, period["start_date"], period["end_date"])
    milestones, milestone_dates = compute_milestone_metrics(child_id, period["start_date"], period["end_date"])

    # Periode SEBELUMNYA — CUMA buat comparisons (metrik penuhnya nggak
    # ikut dikembalikan ke klien, biar payload nggak dobel-besar tanpa
    # guna — cukup current/previous/change/percent_change per metrik).
    prev_feeding, _ = compute_feeding_metrics(child_id, period["prev_start_date"], period["prev_end_date"], days)
    prev_sleep, _ = compute_sleep_metrics(child_id, period["prev_start_date"], period["prev_end_date"], days)
    prev_diaper, _ = compute_diaper_metrics(child_id, period["prev_start_date"], period["prev_end_date"], days)
    prev_pumping, _ = compute_pumping_metrics(child_id, period["prev_start_date"], period["prev_end_date"], days)
    prev_activity, _ = compute_activity_metrics(child_id, period["prev_start_date"], period["prev_end_date"], days)

    comparisons = {
        "feeding_count": build_comparison(feeding["total_events"], prev_feeding["total_events"]),
        # feeding_volume_ml/pumping_volume_ml/activity_duration_minutes:
        # `None` di salah satu sisi (lewat _measured_total_or_none) kalau
        # periode itu punya event tapi TIDAK SATU PUN punya nilai
        # terukur — biar nggak ada penurunan/kenaikan palsu (mis. -100%)
        # yang keluar cuma karena volume/durasinya belum sempat diisi,
        # BUKAN karena beneran turun jadi nol (requirement review #2).
        "feeding_volume_ml": build_comparison(
            _measured_total_or_none(feeding["total_volume_ml"], feeding["total_events"], feeding["events_with_volume"]),
            _measured_total_or_none(
                prev_feeding["total_volume_ml"], prev_feeding["total_events"], prev_feeding["events_with_volume"]
            ),
        ),
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

    # SEMUA kategori record yang didukung Smart Insights ikut menentukan
    # has_any_data/days_with_records — BUKAN cuma 6 kategori "harian"
    # (bug review pasca-Phase-1: anak yang catatannya CUMA growth/health/
    # milestone di periode ini sebelumnya salah dianggap "belum ada data
    # sama sekali", lihat backend/tests/test_insights.py).
    all_dates = (
        feeding_dates | sleep_dates | diaper_dates | pumping_dates | activity_dates | mood_dates
        | growth_dates | health_dates | milestone_dates
    )
    data_quality = {
        "has_any_data": len(all_dates) > 0,
        "days_with_records": len(all_dates),
        "missing_volume_count": feeding["total_events"] - feeding["events_with_volume"],
        "unfinished_sleep_count": sleep["unfinished_session_count"],
    }

    metrics = {
        "feeding": feeding,
        "sleep": sleep,
        "diaper": diaper,
        "pumping": pumping,
        "growth": growth,
        "health": health,
        "activity": activity,
        "mood": mood,
        "milestones": milestones,
    }

    insights = build_insights(metrics, comparisons, data_quality)

    return {
        "period": {
            "key": period["key"],
            "start_date": period["start_date"].isoformat(),
            "end_date": period["end_date"].isoformat(),
            "timezone": "Asia/Jakarta",
            "days": period["days"],
        },
        "previous_period": {
            "start_date": period["prev_start_date"].isoformat(),
            "end_date": period["prev_end_date"].isoformat(),
        },
        "metrics": metrics,
        "comparisons": comparisons,
        "insights": insights,
        "data_quality": data_quality,
    }
