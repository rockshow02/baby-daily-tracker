"""
Bersihin baris tabel idempotency_keys yang udah kadaluarsa.

Tabel ini nyimpen 1 baris per request "create log" offline-queueable yang
punya idempotency key (lihat utils/idempotency.py) — dipakai buat nolak
bikin record dobel kalau klien retry request yang sama. Baris-baris ini
cuma berguna selama JENDELA RETRY OFFLINE (bisa berhari-hari kalau HP-nya
lama nggak online, tapi nggak akan pernah bertahun-tahun) — dibiarin
numpuk terus tanpa batas bakal bikin tabelnya makin gede tanpa manfaat.

SENGAJA TIDAK dipanggil otomatis pas app start (lihat app.py) — jalanin
manual atau lewat scheduled task, biar predictable dan gampang diaudit.

CARA PAKAI (lokal atau di Bash console PythonAnywhere):
  cd ~/baby-daily-tracker/backend
  python scripts/cleanup_idempotency_keys.py               # hapus yang > 90 hari
  python scripts/cleanup_idempotency_keys.py --days 60      # ubah masa retensi
  python scripts/cleanup_idempotency_keys.py --dry-run      # cuma nampilin, nggak hapus

CARA JADWALIN (PythonAnywhere, tab "Tasks"):
  Tambah scheduled task MINGGUAN (nggak perlu harian — data ini nggak
  time-sensitive), jam berapa aja yang jarang ada trafik, misal 03:00 UTC:
    python3.10 /home/USERNAME/baby-daily-tracker/backend/scripts/cleanup_idempotency_keys.py --days 90
  (Free tier PythonAnywhere cuma dapet 1 scheduled task — kalau tab Tasks
  udah dipakai buat send_reminders.py, gabungin dua-duanya jadi 1 script
  kecil yang manggil keduanya, atau upgrade paket buat slot task tambahan.)
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from utils.idempotency import cleanup_expired_idempotency_keys

DEFAULT_RETENTION_DAYS = 90


def run(days=DEFAULT_RETENTION_DAYS, dry_run=False):
    cutoff = datetime.utcnow() - timedelta(days=days)
    app = create_app()
    with app.app_context():
        if dry_run:
            from models import IdempotencyKey

            count = IdempotencyKey.query.filter(IdempotencyKey.created_at < cutoff).count()
            print(f"[dry-run] {count} baris idempotency_keys lebih tua dari {days} hari (sebelum {cutoff.isoformat()}Z) — TIDAK dihapus.")
            return count

        deleted = cleanup_expired_idempotency_keys(cutoff)
        db.session.commit()
        print(f"Selesai: {deleted} baris idempotency_keys lebih tua dari {days} hari dihapus.")
        return deleted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_RETENTION_DAYS, help="Masa retensi dalam hari (default: 90)")
    parser.add_argument("--dry-run", action="store_true", help="Cuma hitung & tampilin, jangan hapus apa-apa")
    args = parser.parse_args()
    run(days=args.days, dry_run=args.dry_run)
