"""
Migrasi database production TANPA menghapus data yang udah ada.

BEDA dari pola "hapus tracker.db + reset + seed ulang" yang kita pakai di
staging — script ini AMAN dijalankan di database yang udah ada isinya
(production, punya data asli hasil import PiyoLog dkk). Cuma nambah kolom
baru ke tabel yang udah ada, dan bikin tabel baru yang belum ada — nggak
pernah hapus/timpa data.

Aman dijalankan berulang kali (idempotent) — kolom/tabel yang udah ada
otomatis dilewatin, nggak dicoba ditambah lagi.

CARA PAKAI (di Bash console PythonAnywhere akun production):
  cd ~/baby-daily-tracker/backend
  python scripts/migrate_production.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, inspect

from app import create_app
from extensions import db

# (nama_tabel, nama_kolom, definisi_SQL_kolom) — kolom baru yang mungkin
# belum ada di database production yang udah lama nggak di-reset
COLUMNS_TO_ENSURE = [
    ("users", "telegram_chat_id", "VARCHAR(50)"),
    ("children", "nickname", "VARCHAR(30)"),
    ("articles", "last_tip_shown_at", "DATETIME"),
    # fitur "log siapa yang catat" - atribusi per entri
    ("feeding_logs", "created_by_user_id", "INTEGER"),
    ("sleep_logs", "created_by_user_id", "INTEGER"),
    ("diaper_logs", "created_by_user_id", "INTEGER"),
    ("pumping_logs", "created_by_user_id", "INTEGER"),
    ("activity_logs", "created_by_user_id", "INTEGER"),
    ("growth_measurements", "created_by_user_id", "INTEGER"),
    ("doctor_visit_logs", "created_by_user_id", "INTEGER"),
    ("temperature_logs", "created_by_user_id", "INTEGER"),
    ("illness_logs", "created_by_user_id", "INTEGER"),
    ("medication_logs", "created_by_user_id", "INTEGER"),
    ("mood_logs", "created_by_user_id", "INTEGER"),
    ("milestone_logs", "created_by_user_id", "INTEGER"),
]


def migrate():
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()

        print("=== Cek & tambah kolom yang mungkin belum ada ===")
        for table_name, column_name, column_def in COLUMNS_TO_ENSURE:
            if table_name not in existing_tables:
                print(f"  Tabel '{table_name}' belum ada, dilewatin (bakal dibikin lengkap di langkah berikutnya)")
                continue

            existing_columns = [c["name"] for c in inspector.get_columns(table_name)]
            if column_name in existing_columns:
                print(f"  '{table_name}.{column_name}' udah ada, dilewatin")
                continue

            print(f"  Nambahin '{table_name}.{column_name}'...")
            with db.engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"))
                conn.commit()
            print(f"    OK")

        print("\n=== Bikin tabel yang belum ada (kayak 'articles') ===")
        print("  Data di tabel yang UDAH ADA nggak akan disentuh sama sekali.")
        db.create_all()
        print("  Selesai.")

        print("\n=== Verifikasi akhir ===")
        inspector = inspect(db.engine)
        final_tables = sorted(inspector.get_table_names())
        print(f"  Total tabel sekarang: {len(final_tables)}")
        for t in final_tables:
            print(f"    - {t}")


if __name__ == "__main__":
    migrate()