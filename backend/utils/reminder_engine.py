"""
Care Reminders & Schedules — Phase 1 (lihat backend/docs/REMINDERS.md
buat kontrak lengkapnya).

Mesin MURNI-Python di sini TIDAK PERNAH manggil jam sistem sendiri
(`now`/`today` SELALU parameter dari pemanggil, PERSIS pola
`utils/insights_engine.py`) — ini INTI dari arsitektur "tanpa scheduler
background": PythonAnywhere Free nggak punya proses yang bisa jalan di
latar belakang buat nge-update status pengingat TEPAT pada waktunya,
jadi status okurensi (upcoming/due/overdue/completed/skipped) SELALU
dihitung ULANG dari nol setiap kali diminta — lewat query REST biasa
(GET /reminders, dashboard, reconnect, interval polling frontend),
BUKAN disimpan/diperbarui oleh proses terus-menerus. Backend TETAP
OTORITATIF buat status ini — klien TIDAK PERNAH dipercaya ngirim status
sendiri, endpoint aksi (complete/skip) selalu menghitung ulang status
occurrence-nya sendiri sebelum menerima aksi.
"""
import re
from datetime import datetime, timedelta

REMINDER_TYPES = ("medication", "doctor_visit", "vaccination", "pumping", "general")
RECURRENCE_VALUES = ("none", "daily")
OCCURRENCE_STATUSES = ("completed", "skipped")  # 'pending' TIDAK PERNAH disimpan — lihat models.py:ReminderAction

# Log yang boleh ditautkan lewat alur "Catat sekarang" (requirement:
# jangan otomatis bikin record medikasi/vaksinasi cuma gara-gara
# pengingatnya jatuh tempo — link ini CUMA keisi SETELAH caregiver
# beneran nyimpen catatannya sendiri).
LINKABLE_LOG_TYPES = ("medication_log", "pumping_log", "doctor_visit")

OCCURRENCE_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# --------------------------------------------------------------------------
# Kebijakan grace-window — HEURISTIK PRODUK (dipilih biar UI nggak
# nunjukin "due" cuma karena telat semenit, dan nggak buru-buru nunjukin
# "overdue" walau caregiver mungkin masih di tengah proses ngerjain),
# BUKAN standar medis. Didokumentasikan ulang di backend/docs/REMINDERS.md.
# --------------------------------------------------------------------------
UPCOMING_THRESHOLD_MINUTES = 15  # occurrence_at - now > ini -> "upcoming"
DUE_AFTER_MINUTES = 30           # now - occurrence_at <= ini -> masih "due"

# Batas berapa hari ke belakang okurensi HARIAN yang BELUM di-resolve
# (belum completed/skipped) tetap ditampilkan sebagai overdue di daftar
# — MENCEGAH query/komputasi nggak terbatas buat reminder yang udah lama
# aktif (requirement: "avoid unbounded historical queries" & "bounded
# number of recent overdue occurrences").
DAILY_LOOKBACK_DAYS = 14


def compute_occurrence_state(occurrence_at, now, resolved_status=None):
    """
    `resolved_status`: None (belum ada ReminderAction — "pending"),
    atau "completed"/"skipped" (SUDAH ada). Balikin salah satu dari
    "upcoming" | "due" | "overdue" | "completed" | "skipped".
    """
    if resolved_status in OCCURRENCE_STATUSES:
        return resolved_status
    delta_minutes = (now - occurrence_at).total_seconds() / 60
    if delta_minutes < -UPCOMING_THRESHOLD_MINUTES:
        return "upcoming"
    if delta_minutes <= DUE_AFTER_MINUTES:
        return "due"
    return "overdue"


def occurrence_key_for_date(d):
    """Kunci okurensi = tanggal WIB lokal apa adanya (ISO 'YYYY-MM-DD') — SAMA format buat 'none' maupun 'daily'."""
    return d.isoformat()


def parse_occurrence_key(key):
    """Balikin `date` kalau `key` format 'YYYY-MM-DD' yang VALID (bukan cuma cocok regex, tanggalnya beneran ada), None kalau nggak."""
    if not isinstance(key, str) or not OCCURRENCE_KEY_RE.match(key):
        return None
    try:
        return datetime.strptime(key, "%Y-%m-%d").date()
    except ValueError:
        return None


def occurrence_datetime_for_date(scheduled_at, occ_date):
    """Datetime okurensi buat 1 tanggal tertentu — tanggal `occ_date`, jam:menit:detik dari `scheduled_at` reminder-nya."""
    return datetime.combine(occ_date, scheduled_at.time())


def valid_occurrence_date_range(reminder_scheduled_at, recurrence, today):
    """
    (earliest_date, latest_date) inklusif — rentang tanggal yang SAH
    diminta lewat endpoint complete/skip untuk reminder ini SEKARANG, atau
    `None` kalau TIDAK ADA tanggal yang sah sama sekali right now (dipilih
    SENGAJA daripada balikin rentang "kebalik"/kosong ambigu semacam
    `(besok, hari_ini)` — itu gampang kepakai salah sebagai rentang beneran
    kalau pemanggil lupa nge-cek, jadi `None` yang eksplisit di sini WAJIB
    dicek dulu sebelum dipakai, lihat routes/reminder_routes.py).

    TERPISAH dari occurrence yang DITAMPILKAN di daftar (fungsi
    `compute_reminder_occurrences` di bawah, yang cuma nunjukin SEBAGIAN
    buat UI) — endpoint aksi tetap boleh nerima occurrence_key historis
    APA PUN dalam batas ini, nggak melulu yang kebetulan lagi tampil di
    halaman list saat itu.

    Okurensi MASA DEPAN (`> today`) — baik reminder 'none' yang jadwalnya
    sendiri belum tiba, MAUPUN reminder 'daily' yang `start_date`-nya
    sendiri belum tiba — SELALU ditolak (`None`), bukan cuma disembunyikan
    dari tampilan (requirement review: "future one-time occurrence must
    not be acted on early"). Okurensi SEBELUM reminder ini dibuat,
    ATAUPUN LEBIH LAMA dari `DAILY_LOOKBACK_DAYS` (khusus 'daily') juga
    selalu ditolak — mencegah aksi di luar jangkauan historis yang wajar.
    """
    start_date = reminder_scheduled_at.date()
    if start_date > today:
        # Jadwalnya sendiri (buat 'none') ATAU tanggal MULAI-nya (buat
        # 'daily') belum tiba -- TIDAK ADA okurensi yang bisa diaksi sama
        # sekali hari ini, apa pun occurrence_key yang dikirim.
        return None
    if recurrence == "none":
        return start_date, start_date
    lookback_start = max(start_date, today - timedelta(days=DAILY_LOOKBACK_DAYS))
    return lookback_start, today


def _build_occurrence_dict(scheduled_at, occ_date, action, now):
    occ_at = occurrence_datetime_for_date(scheduled_at, occ_date)
    resolved_status = action.status if action else None
    return {
        "occurrence_key": occurrence_key_for_date(occ_date),
        "occurrence_at": occ_at,
        "state": compute_occurrence_state(occ_at, now, resolved_status),
        "status": resolved_status,
        "acted_at": action.acted_at if action else None,
        "acted_by_user_id": action.acted_by_user_id if action else None,
        "acted_by_name": (action.actor.name if action.actor else None) if action else None,
        "linked_log_type": action.linked_log_type if action else None,
        "linked_log_id": action.linked_log_id if action else None,
    }


def compute_reminder_occurrences(reminder, actions_by_date, today, now):
    """
    List dict okurensi (lihat `_build_occurrence_dict`), TERURUT tanggal
    naik, DIBATASI buat ditampilkan di UI — MAKSIMAL `DAILY_LOOKBACK_DAYS
    + 1` baris, TIDAK PERNAH lebih walau reminder-nya udah aktif
    berbulan-bulan:

      - 'none': CUMA 1 okurensi (`scheduled_at.date()`), SELALU
        disertakan apa pun statusnya — reminder sekali-jalan cuma punya
        SATU kesempatan, jadi harus selalu kelihatan.
      - 'daily': okurensi HARI INI **+ semua hari dalam jendela
        `DAILY_LOOKBACK_DAYS` ke belakang**, APA PUN statusnya (upcoming/
        due/overdue MAUPUN yang udah completed/skipped) — jendelanya
        SENDIRI yang membatasi jumlah barisnya (bukan penyaringan status
        per hari), biar UI punya cukup data buat 3 bagian yang beda
        sekaligus: due/overdue yang PERLU ditindaklanjuti, DAN riwayat
        completed/skipped TERKINI buat konfirmasi. Okurensi di LUAR
        jendela ini nggak ikut muncul di respons list — TAPI baris
        `ReminderAction`-nya sendiri TETAP permanen di database (nggak
        pernah dihapus/ditimpa), cuma nggak semuanya ditampilkan di 1
        respons list.

    `actions_by_date`: dict {date: ReminderAction} — SEMUA aksi yang
    udah ada buat reminder ini, di-query SEKALI oleh pemanggil (route)
    dan dilewatin ke sini apa adanya, biar fungsi ini TETAP murni/gampang
    dites tanpa perlu koneksi database.
    """
    if not reminder.is_active:
        return []

    start_date = reminder.scheduled_at.date()
    if reminder.recurrence == "none":
        occ_date = start_date
        return [_build_occurrence_dict(reminder.scheduled_at, occ_date, actions_by_date.get(occ_date), now)]

    lookback_start = max(start_date, today - timedelta(days=DAILY_LOOKBACK_DAYS))
    occurrences = []
    d = lookback_start
    while d <= today:
        occurrences.append(_build_occurrence_dict(reminder.scheduled_at, d, actions_by_date.get(d), now))
        d += timedelta(days=1)
    return occurrences


def next_pending_occurrence_at(reminder, actions_by_date, today):
    """
    Datetime okurensi PENDING (belum completed/skipped) BERIKUTNYA buat
    reminder ini, `None` kalau nggak ada lagi (reminder nonaktif, atau
    reminder 'none' yang satu-satunya okurensinya udah di-resolve).
    Dipakai buat ringkasan dashboard ("pengingat berikutnya") — dihitung
    TERLEPAS dari batas tampilan `compute_reminder_occurrences` di atas,
    soalnya reminder harian SELALU punya "besok" selama masih aktif
    (rekursinya nggak pernah "habis").

    Reminder yang JADWAL/TANGGAL MULAI-nya sendiri masih di MASA DEPAN
    (`today < start_date`) SELALU balikin `reminder.scheduled_at` APA
    ADANYA — TIDAK PERNAH "hari ini" (requirement review: reminder
    harian yang belum mulai TIDAK PERNAH boleh nunjuk ke okurensi hari
    ini yang sebenernya nggak pernah ada — konsisten sama
    `compute_reminder_occurrences`/`valid_occurrence_date_range` di
    atas, yang SAMA-SAMA nggak pernah menghasilkan/menerima okurensi
    sebelum `start_date`).
    """
    if not reminder.is_active:
        return None
    start_date = reminder.scheduled_at.date()
    if today < start_date:
        return reminder.scheduled_at

    if reminder.recurrence == "none":
        if start_date in actions_by_date:
            return None
        return reminder.scheduled_at
    if today not in actions_by_date:
        return occurrence_datetime_for_date(reminder.scheduled_at, today)
    return occurrence_datetime_for_date(reminder.scheduled_at, today + timedelta(days=1))
