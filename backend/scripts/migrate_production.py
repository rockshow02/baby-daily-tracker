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

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from app import create_app
from extensions import db
from models import CaregiverAuditEvent, Child, ChildCaregiver, User

# (nama_tabel, nama_kolom, definisi_SQL_kolom) — kolom baru yang mungkin
# belum ada di database production yang udah lama nggak di-reset
COLUMNS_TO_ENSURE = [
    ("users", "telegram_chat_id", "VARCHAR(50)"),
    ("users", "is_active", "BOOLEAN NOT NULL DEFAULT 1"),
    ("users", "deleted_at", "DATETIME"),
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
    # fingerprint request buat validasi idempotency key (lihat utils/idempotency.py) —
    # tabel idempotency_keys sendiri baru (dibikin otomatis lewat db.create_all() di
    # bawah kalau belum ada), tapi kalau tabelnya SUDAH ada dari deploy branch
    # sebelumnya (mis. udah sempat dicoba di staging) sebelum kolom ini ditambahkan,
    # baris ini yang nambahin kolomnya tanpa nyentuh baris yang udah ada.
    ("idempotency_keys", "fingerprint", "VARCHAR(64)"),
    # Caregiver Roles & Permissions Phase 1 (lihat backend/docs/ROLES_PERMISSIONS.md)
    # — peran yang DIPILIH pemilik pas bikin undangan. DEFAULT 'editor'
    # buat baris undangan LAMA yang dibikin SEBELUM kolom ini ada (PERSIS
    # perilaku lama: caregiver yang gabung lewat undangan lama selalu
    # bisa create/update/delete, sama kayak editor sekarang).
    ("child_invites", "role", "VARCHAR(15) NOT NULL DEFAULT 'editor'"),
]


TABLE_NAME = "caregiver_audit_events"
NEW_TABLE_NAME = "caregiver_audit_events_new"


def _actor_fk_has_ondelete_set_null(inspector):
    """
    True kalau FK `caregiver_audit_events.actor_user_id -> users.id` yang
    ADA SEKARANG di database ini udah punya `ON DELETE SET NULL`. False
    kalau FK-nya ADA tapi TANPA itu (skema lama, sebelum perbaikan Issue 2
    — lihat models.py:CaregiverAuditEvent), atau kalau kolomnya nggak
    ketemu FK sama sekali.
    """
    for fk in inspector.get_foreign_keys(TABLE_NAME):
        if fk.get("constrained_columns") == ["actor_user_id"]:
            return (fk.get("options") or {}).get("ondelete", "").upper() == "SET NULL"
    return False


def _ensure_audit_actor_fk_set_null():
    """
    Migrasi SQLite KHUSUS Issue 2 (lihat backend/docs/AUDIT_TRAIL.md):
    kalau tabel `caregiver_audit_events` UDAH ADA (dibikin sebelum
    `ondelete="SET NULL"` ditambahin ke models.py) DAN FK
    `actor_user_id`-nya BELUM `ON DELETE SET NULL`, bangun ulang tabelnya
    (rename+copy — BUKAN drop+create ulang dari nol) biar FK-nya kekoreksi
    TANPA kehilangan 1 baris pun yang udah ada.

    IDEMPOTEN: kalau tabelnya belum ada sama sekali (db.create_all() di
    bawah bakal bikin dari nol pakai skema TERBARU, otomatis udah bener),
    ATAU FK-nya UDAH `ON DELETE SET NULL` (migrasi ini udah pernah
    jalan), fungsi ini nggak ngapa-ngapain sama sekali.

    Skema tabel BARU (create_table_sql/index-nya) di-generate LANGSUNG
    dari models.py:CaregiverAuditEvent (bukan DDL yang diketik manual di
    sini) — jadi nggak mungkin "ke-drift" beda dari definisi model yang
    beneran dipakai app.

    Kolom yang di-copy dari tabel lama SENGAJA disebut namanya satu-satu
    (bukan `SELECT *`) biar urutan/isinya eksplisit dan gampang diaudit —
    SEMUA nilai baris lama (termasuk actor_user_id yang MASIH nunjuk ke
    user yang valid) disalin APA ADANYA, nggak ada yang diubah/hilang.
    """
    engine = db.engine
    inspector = inspect(engine)
    if TABLE_NAME not in inspector.get_table_names():
        print(f"  '{TABLE_NAME}' belum ada sama sekali — dilewatin (db.create_all() di bawah bakal bikin dari skema terbaru, FK-nya otomatis udah bener).")
        return
    if _actor_fk_has_ondelete_set_null(inspector):
        print(f"  FK '{TABLE_NAME}.actor_user_id' udah 'ON DELETE SET NULL' — dilewatin.")
        return

    print(f"  FK '{TABLE_NAME}.actor_user_id' BELUM 'ON DELETE SET NULL' — bangun ulang tabel (data TETAP dipertahankan)...")

    # MetaData terpisah, isinya SALINAN users+children (biar FK di tabel
    # audit yang baru bisa nemu tabel yang dirujuknya) + salinan
    # caregiver_audit_events yang di-RENAME ke nama sementara — SAMA
    # SEKALI nggak nyentuh db.metadata asli app (yang masih dipakai
    # ORM/db.create_all() di bawah).
    temp_metadata = MetaData()
    User.__table__.to_metadata(temp_metadata)
    Child.__table__.to_metadata(temp_metadata)
    new_table = CaregiverAuditEvent.__table__.to_metadata(temp_metadata, name=NEW_TABLE_NAME)

    dialect = sqlite_dialect.dialect()
    create_table_sql = str(CreateTable(new_table).compile(dialect=dialect))
    # Index dibangun dari tabel ASLI (bukan salinan "_new"-nya) — string
    # SQL-nya udah otomatis nunjuk ke nama tabel FINAL (caregiver_audit_events),
    # jadi tinggal dieksekusi APA ADANYA sesudah langkah RENAME di bawah.
    final_index_sqls = [str(CreateIndex(ix).compile(dialect=dialect)) for ix in CaregiverAuditEvent.__table__.indexes]
    columns_csv = ", ".join(c.name for c in CaregiverAuditEvent.__table__.columns)

    # PRAGMA foreign_keys CUMA bisa diganti di LUAR transaksi aktif —
    # makanya dipakai raw DBAPI connection (bukan db.engine.connect()
    # yang auto-begin transaksi di SQLAlchemy 2.x), biar urutannya bisa
    # dikontrol persis: OFF -> (rebuild, 1 transaksi) -> ON lagi, SEBELUM
    # koneksinya balik ke pool. Dimatikan CUMA buat durasi migrasi INI
    # doang — SAMA SEKALI bukan pengaturan permanen aplikasi (yang
    # nyalain-nya justru extensions.py, lihat komentar di sana).
    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")
        cursor.execute(create_table_sql)
        cursor.execute(
            f"INSERT INTO {NEW_TABLE_NAME} ({columns_csv}) SELECT {columns_csv} FROM {TABLE_NAME}"
        )
        cursor.execute(f"DROP TABLE {TABLE_NAME}")
        cursor.execute(f"ALTER TABLE {NEW_TABLE_NAME} RENAME TO {TABLE_NAME}")
        for stmt in final_index_sqls:
            cursor.execute(stmt)
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        cursor = raw_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        integrity_violations = cursor.execute("PRAGMA foreign_key_check").fetchall()
        cursor.close()
        raw_conn.close()

    if integrity_violations:
        print(f"  PERINGATAN: PRAGMA foreign_key_check nemu {len(integrity_violations)} masalah setelah migrasi FK!")
    else:
        print(f"  OK: tabel '{TABLE_NAME}' udah dibangun ulang, FK 'actor_user_id' sekarang 'ON DELETE SET NULL', semua baris lama tetap ada.")


def _child_caregivers_has_role_check_constraint(engine):
    """
    True kalau tabel `child_caregivers` di database ini UDAH punya CHECK
    constraint `role IN ('editor','viewer')` (skema Phase 1 terbaru — lihat
    models.py:ChildCaregiver). Dicek lewat `sqlite_master.sql` mentah
    (bukan `inspector.get_check_constraints()`) — cara paling sederhana &
    stabil buat SQLite, nggak bergantung versi SQLAlchemy tertentu buat
    refleksi CHECK constraint.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='child_caregivers'")
        ).fetchone()
    if not row or not row[0]:
        return False
    return "CHECK" in row[0].upper()


def _migrate_child_caregiver_roles():
    """
    Migrasi SQLite KHUSUS Caregiver Roles & Permissions Phase 1 (lihat
    backend/docs/ROLES_PERMISSIONS.md): skema LAMA nyimpen `role='owner'`
    (baris redundan buat si pemilik — status pemilik SEKARANG SATU-
    SATUNYA sumber kebenarannya `Child.user_id`, lihat models.py:
    ChildCaregiver docstring) dan `role='caregiver'` (caregiver biasa,
    yang sekarang jadi 'editor'). Migrasi ini:

      1. BUANG baris `role='owner'` (redundan, nggak pernah lagi
         dipakai/dibaca kode Phase 1 — resolve_role() SELALU cek
         Child.user_id duluan, nggak pernah nengok baris ini).
      2. UBAH `role='caregiver'` jadi `'editor'` (PERSIS perilaku lama —
         caregiver yang diundang SEBELUM fitur peran ini selalu bisa
         create/update/delete, sama kayak editor sekarang).
      3. Tegakkan CHECK constraint `role IN ('editor','viewer')` di
         skema tabel barunya (SQLite nggak bisa ALTER TABLE nambah CHECK
         ke tabel yang udah ada, jadi tabelnya dibangun ulang — rename +
         copy DENGAN TRANSFORMASI, bukan drop+create ulang dari nol).

    IDEMPOTEN: kalau tabelnya belum ada sama sekali (db.create_all() di
    bawah bakal bikin dari skema terbaru, otomatis udah bener), ATAU
    CHECK constraint-nya UDAH ada (migrasi ini udah pernah jalan), fungsi
    ini nggak ngapa-ngapain sama sekali.
    """
    engine = db.engine
    inspector = inspect(engine)
    if "child_caregivers" not in inspector.get_table_names():
        print("  'child_caregivers' belum ada sama sekali — dilewatin (db.create_all() di bawah bakal bikin dari skema terbaru).")
        return
    if _child_caregivers_has_role_check_constraint(engine):
        print("  'child_caregivers.role' udah punya CHECK constraint (editor/viewer) — dilewatin.")
        return

    print("  'child_caregivers' masih skema lama (role bisa 'owner'/'caregiver') — bangun ulang tabel (data non-owner TETAP dipertahankan)...")

    temp_metadata = MetaData()
    Child.__table__.to_metadata(temp_metadata)
    User.__table__.to_metadata(temp_metadata)
    new_table = ChildCaregiver.__table__.to_metadata(temp_metadata, name="child_caregivers_new")

    dialect = sqlite_dialect.dialect()
    create_table_sql = str(CreateTable(new_table).compile(dialect=dialect))
    final_index_sqls = [str(CreateIndex(ix).compile(dialect=dialect)) for ix in ChildCaregiver.__table__.indexes]

    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")
        cursor.execute(create_table_sql)
        # Transformasi data pas nyalin: 'owner' DIBUANG (WHERE role !=
        # 'owner'), 'caregiver' jadi 'editor' (CASE), nilai lain (udah
        # 'editor'/'viewer', kalau migrasi ini kebetulan dijalankan di
        # skema yang sebagian udah termigrasi) disalin apa adanya.
        cursor.execute(
            "INSERT INTO child_caregivers_new (id, child_id, user_id, role, created_at) "
            "SELECT id, child_id, user_id, "
            "CASE WHEN role = 'caregiver' THEN 'editor' ELSE role END, "
            "created_at "
            "FROM child_caregivers WHERE role != 'owner'"
        )
        cursor.execute("DROP TABLE child_caregivers")
        cursor.execute("ALTER TABLE child_caregivers_new RENAME TO child_caregivers")
        for stmt in final_index_sqls:
            cursor.execute(stmt)
        raw_conn.commit()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        cursor = raw_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        integrity_violations = cursor.execute("PRAGMA foreign_key_check").fetchall()
        cursor.close()
        raw_conn.close()

    if integrity_violations:
        print(f"  PERINGATAN: PRAGMA foreign_key_check nemu {len(integrity_violations)} masalah setelah migrasi peran!")
    else:
        print("  OK: 'child_caregivers' dibangun ulang — baris 'owner' dibuang, 'caregiver' jadi 'editor', CHECK constraint aktif.")


def migrate():
    app = create_app()
    with app.app_context():
        print("=== Migrasi FK 'caregiver_audit_events.actor_user_id' (ON DELETE SET NULL) ===")
        _ensure_audit_actor_fk_set_null()

        print("\n=== Migrasi peran 'child_caregivers.role' (Caregiver Roles & Permissions Phase 1) ===")
        _migrate_child_caregiver_roles()

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

        print("\n=== Bikin tabel yang belum ada (kayak 'articles', 'caregiver_audit_events', 'reminders') ===")
        print("  Data di tabel yang UDAH ADA nggak akan disentuh sama sekali.")
        # 'caregiver_audit_events' (Caregiver Audit Trail Phase 1 — lihat
        # backend/docs/AUDIT_TRAIL.md) DAN 'reminders'/'reminder_actions'
        # (Care Reminders & Schedules Phase 1 — lihat
        # backend/docs/REMINDERS.md) SENGAJA nggak perlu masuk daftar
        # COLUMNS_TO_ENSURE di atas: semuanya tabel BARU (bukan kolom baru
        # di tabel lama), jadi db.create_all() di bawah ini SUDAH CUKUP
        # buat bikinnya — nggak ada ALTER TABLE yang perlu ditulis manual,
        # dan nggak ada baris lama yang ke-touch (tabel-tabel ini emang
        # belum ada baris apa pun sebelum migrasi ini). db.create_all()
        # TIDAK PERNAH nge-drop/re-create tabel yang UDAH ada, cuma
        # nambah yang belum ada.
        db.create_all()
        print("  Selesai.")

        print("\n=== Verifikasi akhir ===")
        inspector = inspect(db.engine)
        final_tables = sorted(inspector.get_table_names())
        print(f"  Total tabel sekarang: {len(final_tables)}")
        for t in final_tables:
            print(f"    - {t}")

        if "caregiver_audit_events" in final_tables:
            print("\n  OK: tabel 'caregiver_audit_events' (Caregiver Audit Trail Phase 1) ada.")
        else:
            print("\n  PERINGATAN: tabel 'caregiver_audit_events' TIDAK ditemukan setelah migrasi!")

        # Care Reminders & Schedules Phase 1 (lihat backend/docs/REMINDERS.md)
        # — 'reminders'/'reminder_actions' SAMA PERSIS pola
        # 'caregiver_audit_events' di atas: tabel BARU (bukan kolom baru
        # di tabel lama), db.create_all() di atas SUDAH CUKUP bikinnya,
        # nggak ada baris lama yang perlu ditransformasi/ditulis manual.
        if "reminders" in final_tables and "reminder_actions" in final_tables:
            print("  OK: tabel 'reminders' dan 'reminder_actions' (Care Reminders & Schedules Phase 1) ada.")
        else:
            print("  PERINGATAN: tabel 'reminders'/'reminder_actions' TIDAK ditemukan setelah migrasi!")

        # Caregiver Handover Summary Phase 1 (lihat
        # backend/docs/CAREGIVER_HANDOVER.md) — pola SAMA PERSIS
        # 'reminders'/'caregiver_audit_events' di atas: 2 tabel BARU,
        # db.create_all() di atas SUDAH CUKUP (termasuk partial unique
        # index "1 handover terbuka per anak" — lihat
        # models.py:CaregiverHandover), tidak ada baris lama yang perlu
        # ditransformasi.
        if "caregiver_handovers" in final_tables and "caregiver_handover_acknowledgements" in final_tables:
            print("  OK: tabel 'caregiver_handovers' dan 'caregiver_handover_acknowledgements' (Caregiver Handover Summary Phase 1) ada.")
        else:
            print("  PERINGATAN: tabel 'caregiver_handovers'/'caregiver_handover_acknowledgements' TIDAK ditemukan setelah migrasi!")


if __name__ == "__main__":
    migrate()
