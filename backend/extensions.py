import sqlite3

from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
cors = CORS()


@event.listens_for(Engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, connection_record):
    """
    SQLite MATIIN foreign-key enforcement per default, per KONEKSI (bukan
    per file) — kalau nggak dinyalain manual di sini, FK kayak
    `CaregiverAuditEvent.actor_user_id` (ondelete="SET NULL", lihat
    models.py) CUMA dekorasi di skema doang, nggak pernah beneran
    ditegakkan SQLite pas ada DELETE yang mestinya mentrigger-nya.

    Listener GLOBAL (Engine.connect, bukan cuma engine app ini) supaya
    PERMANEN buat SEMUA koneksi SQLite yang dibikin proses ini — endpoint
    publik, script migrasi, maupun test — bukan cuma dinyalain sesaat pas
    migrasi doang. Satu-satunya tempat FK enforcement ini boleh dimatikan
    SEMENTARA adalah di dalam migrasi rebuild tabel SQLite sendiri
    (scripts/migrate_production.py:_ensure_audit_actor_fk_set_null),
    yang WAJIB nyalain balik sebelum keluar — TIDAK PERNAH dimatikan
    sebagai pengaturan aplikasi yang permanen.

    No-op buat dialect non-SQLite (Postgres/MySQL, dst — dicek lewat
    isinstance ke driver sqlite3 bawaan Python, bukan asumsi config app
    ini SQLite doang) — aman dibiarkan terpasang biar pun aplikasi ini
    suatu saat pindah database lain.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
