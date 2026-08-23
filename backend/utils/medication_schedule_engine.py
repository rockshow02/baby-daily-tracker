"""
Medication Schedule & Adherence — Phase 1 (lihat
backend/docs/MEDICATION_SCHEDULE.md buat kontrak lengkapnya).

REUSE, BUKAN mesin pengingat saingan: status per-okurensi
(upcoming/due/overdue) dipakai LANGSUNG dari
`utils/reminder_engine.py:compute_occurrence_state` -- ambang
grace-window (15 menit sebelum / 30 menit sesudah) SAMA PERSIS, SATU
sumber kebenaran, bukan disalin ulang di sini. Yang BENERAN baru di
modul ini CUMA hal yang belum ada di reminder_engine.py: 1 jadwal bisa
punya BEBERAPA jam pemberian per hari (`times_of_day`), jadi okurensi
per hari BUKAN 1 tapi banyak.

Mesin MURNI-Python di sini TIDAK PERNAH manggil jam sistem sendiri
(`now`/`today` SELALU parameter dari pemanggil) -- PERSIS prinsip
`utils/reminder_engine.py`/`utils/insights_engine.py`, arsitektur
"tanpa scheduler background" PythonAnywhere Free.
"""
import re
from datetime import datetime, time, timedelta

from utils.reminder_engine import DUE_AFTER_MINUTES, compute_occurrence_state

OCCURRENCE_STATUSES = ("administered", "skipped")  # 'pending' TIDAK PERNAH disimpan -- lihat models.py:MedicationDoseAction

# Batas berapa hari ke belakang okurensi yang BELUM di-resolve tetap
# ditampilkan di timeline -- SAMA PERSIS DAILY_LOOKBACK_DAYS di
# utils/reminder_engine.py (satu kebijakan produk, dua mesin yang
# berbagi angka yang sama, bukan konstanta baru yang bisa hanyut).
LOOKBACK_DAYS = 14

# Batas praktis (requirement: "set practical limits on the number of
# daily times and regimen duration") -- mencegah jadwal yang nggak
# masuk akal (mis. 50 kali/hari, ATAUPUN regimen "aktif" 30 tahun) yang
# bikin komputasi okurensi meledak walau masih "sah" secara tipe data.
MAX_TIMES_PER_DAY = 6
MAX_REGIMEN_DAYS = 366

MEDICATION_NAME_MAX_LEN = 150
INSTRUCTIONS_MAX_LEN = 500

# Allowlist satuan dosis -- KOMPATIBEL sama kolom bebas-teks
# `MedicationLog.dosage` yang sudah ada (mis. "0.8 ml", "1 sendok
# takar") -- schedule ini nyimpen `dose_value`+`dose_unit` TERPISAH
# (buat validasi/agregasi), lalu digabung jadi string yang SAMA
# formatnya pas bikin MedicationLog (lihat routes/medication_schedule_routes.py).
DOSE_UNITS = (
    "ml", "mg", "mcg", "tetes", "sendok_takar", "tablet", "kapsul", "sachet", "puff", "unit",
)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_OCCURRENCE_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):([0-5]\d)$")


class ScheduleValidationError(ValueError):
    """Input jadwal/aksi nggak valid -- route menangkap ini, balas 400."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def validate_medication_name(raw):
    if not isinstance(raw, str) or not (1 <= len(raw.strip()) <= MEDICATION_NAME_MAX_LEN):
        raise ScheduleValidationError(f"Nama obat wajib diisi (1-{MEDICATION_NAME_MAX_LEN} karakter)")
    return raw.strip()


def validate_dose(dose_value, dose_unit):
    """
    (dose_value_atau_None, dose_unit_atau_None) -- BERPASANGAN, dua-
    duanya diisi ATAUPUN dua-duanya kosong (requirement: "dose must be
    positive when supplied" -- angka tanpa satuan, atau satuan tanpa
    angka, sama-sama nggak berarti apa-apa buat caregiver lain yang baca).
    """
    if dose_value is None and dose_unit is None:
        return None, None
    if dose_value is None or dose_unit is None:
        raise ScheduleValidationError("Jumlah dosis dan satuan dosis harus diisi bersamaan")
    if isinstance(dose_value, bool) or not isinstance(dose_value, (int, float)):
        raise ScheduleValidationError("Jumlah dosis harus berupa angka")
    if dose_value <= 0:
        raise ScheduleValidationError("Jumlah dosis harus lebih dari 0")
    if dose_unit not in DOSE_UNITS:
        raise ScheduleValidationError(f"Satuan dosis harus salah satu dari: {', '.join(DOSE_UNITS)}")
    return float(dose_value), dose_unit


def validate_instructions(raw):
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ScheduleValidationError("Instruksi harus berupa teks")
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) > INSTRUCTIONS_MAX_LEN:
        raise ScheduleValidationError(f"Instruksi maksimal {INSTRUCTIONS_MAX_LEN} karakter")
    return normalized or None


def validate_times_of_day(raw):
    """List string "HH:MM" -> list TERNORMALISASI (unik, terurut), atau raise."""
    if not isinstance(raw, list) or len(raw) == 0:
        raise ScheduleValidationError("Minimal 1 jam pemberian obat wajib diisi")
    if len(raw) > MAX_TIMES_PER_DAY:
        raise ScheduleValidationError(f"Maksimal {MAX_TIMES_PER_DAY} jam pemberian per hari")
    normalized = set()
    for t in raw:
        if not isinstance(t, str) or not _TIME_RE.match(t):
            raise ScheduleValidationError("Format jam pemberian tidak valid, harus HH:MM (00:00-23:59)")
        normalized.add(t)
    return sorted(normalized)


def validate_date_range(start_date, end_date):
    if end_date is not None and end_date < start_date:
        raise ScheduleValidationError("Tanggal selesai tidak boleh sebelum tanggal mulai")
    if end_date is not None and (end_date - start_date).days > MAX_REGIMEN_DAYS:
        raise ScheduleValidationError(f"Durasi jadwal maksimal {MAX_REGIMEN_DAYS} hari")


def occurrence_key_for(occurrence_at):
    """Kunci okurensi = tanggal+jam WIB lokal apa adanya ('YYYY-MM-DDTHH:MM')."""
    return occurrence_at.strftime("%Y-%m-%dT%H:%M")


def parse_occurrence_key(key):
    """Balikin `datetime` (naive, detik=0) kalau `key` formatnya valid, `None` kalau nggak."""
    if not isinstance(key, str) or not _OCCURRENCE_KEY_RE.match(key):
        return None
    try:
        return datetime.strptime(key, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def _schedule_range_end_date(schedule, today):
    """Tanggal AKHIR yang relevan buat schedule ini per hari ini -- lebih awal dari `end_date` (kalau ada) ATAU `today`, mana yang duluan."""
    return min(schedule.end_date, today) if schedule.end_date else today


def valid_occurrence_range(schedule, today):
    """
    (earliest_dt, latest_dt) inklusif -- rentang DATETIME yang SAH
    diminta lewat endpoint administer/skip untuk schedule ini SEKARANG,
    atau `None` kalau TIDAK ADA sama sekali (pola SAMA PERSIS
    `utils/reminder_engine.py:valid_occurrence_date_range` -- `None`
    eksplisit, BUKAN rentang kebalik/ambigu, WAJIB dicek sebelum
    unpacking).

    Okurensi MASA DEPAN (`start_date > today`, jadwal belum mulai)
    SELALU ditolak. Okurensi SETELAH `end_date` (kalau ada) juga SELALU
    ditolak -- regimen yang udah "selesai" nggak bisa diaksi lagi buat
    tanggal setelah itu. Okurensi LEBIH LAMA dari `LOOKBACK_DAYS` juga
    ditolak, sama kebijakan reminder harian.

    CATATAN: fungsi ini CUMA membatasi TANGGAL -- pemanggil (route)
    TETAP wajib cek jam okurensi yang diminta beneran ada di
    `schedule.times_of_day` (lihat routes/medication_schedule_routes.py),
    karena 1 tanggal bisa punya beberapa jam yang sah dan beberapa yang
    nggak.
    """
    if schedule.start_date > today:
        return None
    range_end_date = _schedule_range_end_date(schedule, today)
    if range_end_date < schedule.start_date:
        return None
    lookback_start_date = max(schedule.start_date, today - timedelta(days=LOOKBACK_DAYS))
    if lookback_start_date > range_end_date:
        return None
    earliest_dt = datetime.combine(lookback_start_date, time.min)
    latest_dt = datetime.combine(range_end_date, time.max)
    return earliest_dt, latest_dt


def _build_occurrence_dict(occ_at, action, now):
    resolved_status = action.status if action else None
    return {
        "occurrence_key": occurrence_key_for(occ_at),
        "occurrence_at": occ_at,
        "state": compute_occurrence_state(occ_at, now, resolved_status),
        "status": resolved_status,
        "acted_at": action.acted_at if action else None,
        "acted_by_user_id": action.acted_by_user_id if action else None,
        "acted_by_name": (action.actor.name if action.actor else None) if action else None,
        "medication_log_id": action.medication_log_id if action else None,
    }


def compute_schedule_occurrences(schedule, actions_by_occurrence, today, now):
    """
    List dict okurensi (lihat `_build_occurrence_dict`), TERURUT
    tanggal+jam naik, DIBATASI `LOOKBACK_DAYS` hari ke belakang + hari
    ini (ATAU sampai `end_date` kalau lebih awal) -- MAKSIMAL
    `(LOOKBACK_DAYS + 1) * MAX_TIMES_PER_DAY` baris per schedule, TIDAK
    PERNAH lebih walau schedule-nya udah aktif berbulan-bulan (pola
    SAMA PERSIS `utils/reminder_engine.py:compute_reminder_occurrences`).

    Schedule nonaktif, ATAU yang `start_date`-nya sendiri masih di masa
    depan, balikin `[]` -- BUKAN error, TIDAK PERNAH menghasilkan
    okurensi yang belum "mulai" beneran.

    `actions_by_occurrence`: dict {datetime: MedicationDoseAction} --
    SEMUA aksi yang relevan buat schedule ini, di-query SEKALI oleh
    pemanggil (route) dan dilewatin ke sini apa adanya, biar fungsi ini
    TETAP murni/gampang dites tanpa koneksi database.
    """
    if not schedule.is_active:
        return []
    if schedule.start_date > today:
        return []

    range_end_date = _schedule_range_end_date(schedule, today)
    lookback_start_date = max(schedule.start_date, today - timedelta(days=LOOKBACK_DAYS))
    if lookback_start_date > range_end_date:
        return []

    times = schedule.times_of_day or []
    occurrences = []
    d = lookback_start_date
    while d <= range_end_date:
        for t in times:
            hh, mm = (int(part) for part in t.split(":"))
            occ_at = datetime.combine(d, time(hh, mm))
            occurrences.append(_build_occurrence_dict(occ_at, actions_by_occurrence.get(occ_at), now))
        d += timedelta(days=1)
    return occurrences


def next_actionable_occurrence_at(schedule, actions_by_occurrence, today, now):
    """
    Datetime okurensi PENDING (belum administered/skipped) BERIKUTNYA
    buat schedule ini, `None` kalau nggak ada (schedule nonaktif,
    regimen sudah lewat `end_date`, ATAU semua okurensi sampai sekarang
    sudah di-resolve DAN belum waktunya jam berikutnya hari ini/besok
    -- dihitung dari daftar okurensi TERBATAS `compute_schedule_occurrences`
    di atas, cukup buat "pengingat berikutnya" ringkasan dashboard,
    KONSISTEN sama daftar yang ditampilkan (beda dari reminder harian
    yang okurensi berikutnya bisa "tak terbatas" walau daftar tampilan
    dibatasi -- di sini schedule medication SELALU punya `end_date`
    ATAUPUN dianggap terbatas ke `today`, jadi cukup dicari dari daftar
    yang sudah dihitung).

    Schedule yang `start_date`-nya SENDIRI masih di MASA DEPAN SELALU
    balikin jam pemberian PERTAMA pada `start_date` itu APA ADANYA --
    TIDAK PERNAH `None` (requirement review, pola SAMA PERSIS
    `utils/reminder_engine.py:next_pending_occurrence_at` -- schedule
    yang belum mulai TETAP harus kelihatan "pengingat berikutnya" di
    dashboard, konsisten sama `compute_schedule_occurrences`/
    `valid_occurrence_range` yang SAMA-SAMA nggak pernah menghasilkan/
    menerima okurensi sebelum `start_date`).
    """
    if not schedule.is_active:
        return None
    if schedule.start_date > today:
        times = schedule.times_of_day or []
        if not times:
            return None
        hh, mm = (int(part) for part in times[0].split(":"))
        return datetime.combine(schedule.start_date, time(hh, mm))

    occurrences = compute_schedule_occurrences(schedule, actions_by_occurrence, today, now)
    for occ in occurrences:
        if occ["status"] is None and occ["occurrence_at"] >= now:
            return occ["occurrence_at"]
    # Nggak ada lagi yang PENDING dan >= now di jendela lookback -- cek
    # jam-jam SISA hari ini yang belum lewat (kalau ada) sebelum
    # nyerah -- ditangani otomatis di atas karena compute_schedule_occurrences
    # sudah menyertakan hari ini penuh.
    return None


def compute_adherence(schedule, actions_by_occurrence, period_start, period_end, now):
    """
    Truth table kepatuhan 1 schedule buat rentang [period_start,
    period_end] (inklusif, tanggal) -- lihat
    backend/docs/MEDICATION_SCHEDULE.md bagian "Formula kepatuhan" buat
    penjelasan lengkap kenapa setiap keputusan di bawah ini diambil.

    PENYEBUT ("expected"): okurensi yang JADWALNYA sudah TIBA
    (`occurrence_at <= now`) DAN jatuh di dalam periode DAN di dalam
    rentang aktif schedule ini (`start_date`..`end_date`/`today`) --
    okurensi MASA DEPAN (`occurrence_at > now`) TIDAK PERNAH dihitung
    "expected", nggak adil menghukum kepatuhan buat dosis yang belum
    waktunya. Regimen yang MULAI DI TENGAH periode otomatis
    tertangani -- occurrence generation nggak pernah menghasilkan
    tanggal sebelum `start_date` schedule-nya sendiri.

    `actions_by_occurrence`: dict {datetime: MedicationDoseAction} --
    SEMUA aksi schedule ini yang occurrence_at-nya ada di
    [period_start, period_end], di-query SEKALI oleh pemanggil.
    """
    range_start = max(schedule.start_date, period_start)
    range_end = min(_schedule_range_end_date(schedule, period_end), period_end)

    result = {
        "expected_count": 0, "administered_count": 0, "skipped_count": 0,
        "overdue_unresolved_count": 0, "on_time_administered_count": 0, "late_administered_count": 0,
    }
    if not schedule.is_active and schedule.end_date is None:
        # Schedule nonaktif TANPA end_date eksplisit -- kapan persisnya
        # dinonaktifkan nggak direkam (requirement: jangan nyimpen
        # status turunan), jadi Phase 1 KONSERVATIF: nggak menghitung
        # ekspektasi apa pun buat schedule nonaktif tanpa end_date yang
        # jelas, daripada menghukum caregiver buat dosis yang secara
        # teknis "seharusnya" tapi schedule-nya sendiri sudah dimatikan.
        return result
    if range_start > range_end:
        return result

    d = range_start
    while d <= range_end:
        for t in (schedule.times_of_day or []):
            hh, mm = (int(part) for part in t.split(":"))
            occ_at = datetime.combine(d, time(hh, mm))
            if occ_at > now:
                continue
            result["expected_count"] += 1
            action = actions_by_occurrence.get(occ_at)
            if action is None:
                if compute_occurrence_state(occ_at, now) == "overdue":
                    result["overdue_unresolved_count"] += 1
                continue
            if action.status == "skipped":
                result["skipped_count"] += 1
            elif action.status == "administered":
                result["administered_count"] += 1
                delta_minutes = (action.acted_at - occ_at).total_seconds() / 60
                if delta_minutes <= DUE_AFTER_MINUTES:
                    result["on_time_administered_count"] += 1
                else:
                    result["late_administered_count"] += 1
        d += timedelta(days=1)
    return result


def adherence_percentage(expected_count, administered_count):
    """
    Persentase kepatuhan (1 desimal), atau `None` kalau `expected_count`
    nol -- TIDAK PERNAH mengarang persentase dari penyebut kosong
    (requirement eksplisit).
    """
    if expected_count <= 0:
        return None
    return round((administered_count / expected_count) * 100, 1)
