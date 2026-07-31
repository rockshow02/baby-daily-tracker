"""
Helper timezone. App ini ditujukan untuk pengguna Indonesia (WIB, UTC+7),
jadi semua timestamp disimpan sebagai wall-clock WIB (naive, tanpa tzinfo)
alih-alih UTC. Ini menyederhanakan query "hari ini" dan mencegah pergeseran
tanggal di sekitar tengah malam.
"""
from datetime import datetime, timezone, timedelta

WIB = timezone(timedelta(hours=7))


def now_wib():
    """Waktu sekarang, wall-clock WIB, naive (tanpa tzinfo) — buat disimpan ke DB."""
    return datetime.now(WIB).replace(tzinfo=None)


def today_wib():
    return now_wib().date()


def to_wib_naive(iso_str):
    """
    Parse ISO string dari client. Kalau ada info timezone (mis. browser kirim
    .toISOString() yang selalu UTC dengan 'Z'), convert ke WIB dulu.
    Kalau naive (tanpa timezone), anggap sudah wall-clock WIB apa adanya.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(WIB).replace(tzinfo=None)