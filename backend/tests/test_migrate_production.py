"""
Test buat scripts/migrate_production.py — KHUSUS bagian tabel baru
'caregiver_audit_events' (Caregiver Audit Trail Phase 1).

SEMUA test di sini pakai file SQLite SEMENTARA (tempfile.mkstemp()),
TIDAK PERNAH menyentuh instance/tracker.db asli.

PENTING soal cara redirect target database-nya: `Config.SQLALCHEMY_DATABASE_URI`
(backend/config.py) itu ATTRIBUTE CLASS yang di-evaluasi SEKALI doang, pas
config.py PERTAMA KALI di-import (biasanya lewat conftest.py, di awal
banget sesi pytest) — `monkeypatch.setenv("DATABASE_URL", ...)` yang
dipanggil BELAKANGAN di dalam 1 test TIDAK PUNYA EFEK APA-APA ke nilai itu
(module Python di-cache, class body nggak dieksekusi ulang). Kalau test
ini nekat pakai env var buat "ngarahin" migrate()/create_app() ke file
sementara, migrate() beneran bakal jalan ke path DEFAULT yang udah
ke-bake dari awal — yaitu instance/tracker.db ASLI. (Ini PERNAH kejadian
beneran pas nulis test ini — lihat riwayat commit/PR buat detailnya —
bikin 1 tabel kosong baru nyangkut di database dev asli sebelum ketauan
dan dibersihin manual.)

Makanya di sini SENGAJA monkeypatch `migrate_production.create_app`
ITU SENDIRI (bukan env var) jadi wrapper yang neruskan `config_overrides`
eksplisit — `config_overrides` DIJAMIN kepakai di setiap panggilan
(diterapkan lewat `app.config.update(...)` di app.py:create_app, bukan
dibaca dari environment yang bisa basi), jadi test ini TIDAK PERNAH
bisa "salah sasaran" ke file lain gara-gara caching import.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BACKEND_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from app import create_app as real_create_app  # noqa: E402
from extensions import db  # noqa: E402
import models  # noqa: E402,F401 — HARUS di-import biar semua tabel kedaftar di db.metadata
import migrate_production  # noqa: E402

REAL_INSTANCE_DB = os.path.join(BACKEND_DIR, "instance", "tracker.db")


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    os.remove(path)  # mulai dari "file belum ada" — db.create_all() yang bikin dari nol
    yield path
    if os.path.exists(path):
        os.remove(path)


def _run_migrate_against(path, monkeypatch):
    """
    Jalanin migrate_production.migrate() BENERAN (logic ALTER TABLE +
    db.create_all() + verifikasi yang SAMA PERSIS kayak dipakai operator),
    tapi dipaksa nunjuk ke `path` (file sementara) lewat config_overrides
    EKSPLISIT — lihat docstring modul buat kenapa ini SATU-SATUNYA cara
    yang aman (bukan env var, yang class attribute config.py udah
    ke-cache dari import pertama sesi pytest).
    """
    created = {}

    def fake_create_app(config_overrides=None):
        overrides = dict(config_overrides or {})
        overrides.setdefault("SQLALCHEMY_DATABASE_URI", f"sqlite:///{path}")
        app = real_create_app(config_overrides=overrides)
        created["app"] = app
        return app

    monkeypatch.setattr(migrate_production, "create_app", fake_create_app)
    migrate_production.migrate()

    # Windows nge-lock file SQLite yang masih ada koneksi kebuka di
    # connection pool — dispose eksplisit di sini biar tempfile.mkstemp()
    # yang dipakai fixture temp_db_path aman di-os.remove() pas teardown
    # (bukan kena PermissionError/WinError 32).
    app = created.get("app")
    if app is not None:
        with app.app_context():
            db.engine.dispose()


def _seed_pre_audit_trail_schema(path):
    """
    Bikin semua tabel KECUALI caregiver_audit_events (simulasi database
    production SEBELUM fitur audit trail ini di-deploy), diisi beberapa
    baris data "lama" (user, child, feeding log) — buat mbuktiin
    migrate() TIDAK NYENTUH baris yang udah ada sama sekali.
    """
    engine = create_engine(f"sqlite:///{path}")
    tables_to_create = [t for t in db.metadata.sorted_tables if t.name != "caregiver_audit_events"]
    db.metadata.create_all(bind=engine, tables=tables_to_create)

    with engine.begin() as conn:
        conn.execute(
            db.metadata.tables["users"].insert(),
            {
                "name": "Legacy User", "email": "legacy@example.com",
                "password_hash": "not-a-real-hash", "telegram_chat_id": None,
                "created_at": datetime(2024, 1, 1),
            },
        )
        conn.execute(
            db.metadata.tables["children"].insert(),
            {
                "user_id": 1, "name": "Legacy Child", "nickname": None,
                "birth_date": date(2024, 1, 1), "gender": "L",
                "birth_weight_kg": None, "birth_height_cm": None, "photo_filename": None,
                "created_at": datetime(2024, 1, 1),
            },
        )
        conn.execute(
            db.metadata.tables["child_caregivers"].insert(),
            {"child_id": 1, "user_id": 1, "role": "owner", "created_at": datetime(2024, 1, 1)},
        )
        conn.execute(
            db.metadata.tables["feeding_logs"].insert(),
            {
                "child_id": 1, "timestamp": datetime(2024, 1, 2, 8, 0, 0), "feed_type": "asi_langsung",
                "duration_minutes": 10, "volume_ml": None, "breast_side": "kiri", "notes": "catatan lama",
                "created_at": datetime(2024, 1, 2, 8, 0, 0), "created_by_user_id": 1,
            },
        )
    engine.dispose()


def _table_names(path):
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _column_names(path, table):
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table});").fetchall()}
    finally:
        conn.close()


def _indexed_columns(path, table):
    """Semua nama kolom yang punya index apa pun (termasuk yang otomatis dari index=True SQLAlchemy)."""
    conn = sqlite3.connect(path)
    try:
        indexes = conn.execute(f"PRAGMA index_list({table});").fetchall()
        cols = set()
        for idx in indexes:
            idx_name = idx[1]
            for col_row in conn.execute(f"PRAGMA index_info({idx_name});").fetchall():
                cols.add(col_row[2])
        return cols
    finally:
        conn.close()


def test_migration_creates_the_new_table(temp_db_path, monkeypatch):
    _seed_pre_audit_trail_schema(temp_db_path)
    assert "caregiver_audit_events" not in _table_names(temp_db_path)

    _run_migrate_against(temp_db_path, monkeypatch)

    assert "caregiver_audit_events" in _table_names(temp_db_path)


def test_migration_creates_expected_columns(temp_db_path, monkeypatch):
    _seed_pre_audit_trail_schema(temp_db_path)
    _run_migrate_against(temp_db_path, monkeypatch)

    columns = _column_names(temp_db_path, "caregiver_audit_events")
    expected = {
        "id", "child_id", "actor_user_id", "action", "entity_type",
        "entity_id", "changed_fields_json", "recorded_at", "created_at",
    }
    assert expected.issubset(columns)


def test_migration_creates_expected_indexes(temp_db_path, monkeypatch):
    _seed_pre_audit_trail_schema(temp_db_path)
    _run_migrate_against(temp_db_path, monkeypatch)

    indexed = _indexed_columns(temp_db_path, "caregiver_audit_events")
    assert "child_id" in indexed
    assert "actor_user_id" in indexed
    assert "created_at" in indexed


def test_rerunning_the_migration_is_safe(temp_db_path, monkeypatch):
    _seed_pre_audit_trail_schema(temp_db_path)
    _run_migrate_against(temp_db_path, monkeypatch)
    _run_migrate_against(temp_db_path, monkeypatch)  # kedua kalinya HARUS nggak error/nggak nambah apa-apa

    assert "caregiver_audit_events" in _table_names(temp_db_path)
    conn = sqlite3.connect(temp_db_path)
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM caregiver_audit_events;").fetchone()
        assert count == 0  # nggak ada baris yang muncul cuma gara-gara migrasi dijalanin
    finally:
        conn.close()


def test_existing_rows_in_other_tables_are_completely_unchanged(temp_db_path, monkeypatch):
    _seed_pre_audit_trail_schema(temp_db_path)
    _run_migrate_against(temp_db_path, monkeypatch)

    conn = sqlite3.connect(temp_db_path)
    try:
        user_row = conn.execute("SELECT name, email FROM users WHERE id = 1;").fetchone()
        assert user_row == ("Legacy User", "legacy@example.com")

        child_row = conn.execute("SELECT name, birth_date FROM children WHERE id = 1;").fetchone()
        assert child_row == ("Legacy Child", "2024-01-01")

        feeding_row = conn.execute(
            "SELECT feed_type, duration_minutes, notes, created_by_user_id FROM feeding_logs WHERE id = 1;"
        ).fetchone()
        assert feeding_row == ("asi_langsung", 10, "catatan lama", 1)
    finally:
        conn.close()


def test_no_historical_audit_events_are_fabricated_for_pre_existing_records(temp_db_path, monkeypatch):
    """
    Requirement eksplisit: migrasi TIDAK PERNAH bikin CaregiverAuditEvent
    palsu buat record lama (feeding_logs id=1 di seed di atas) yang
    dibikin SEBELUM fitur audit trail ini ada — tabelnya harus kebuat
    KOSONG, bukan di-backfill dengan tebakan "create" event.
    """
    _seed_pre_audit_trail_schema(temp_db_path)
    _run_migrate_against(temp_db_path, monkeypatch)

    conn = sqlite3.connect(temp_db_path)
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM caregiver_audit_events;").fetchone()
        assert count == 0
    finally:
        conn.close()


def test_migration_never_touches_the_real_project_database(temp_db_path, monkeypatch):
    real_db_existed_before = os.path.exists(REAL_INSTANCE_DB)
    real_mtime_before = os.path.getmtime(REAL_INSTANCE_DB) if real_db_existed_before else None

    _seed_pre_audit_trail_schema(temp_db_path)
    _run_migrate_against(temp_db_path, monkeypatch)

    assert os.path.exists(REAL_INSTANCE_DB) == real_db_existed_before
    if real_db_existed_before:
        assert os.path.getmtime(REAL_INSTANCE_DB) == real_mtime_before


# --------------------------------------------------------------------------
# Issue 2 — FK `caregiver_audit_events.actor_user_id` harus `ON DELETE
# SET NULL`. Fresh db (db.create_all() dari model terbaru) udah otomatis
# bener (dites di test_migration_creates_expected_columns dkk di atas,
# via _actor_fk_ondelete di bawah). Bagian ini KHUSUS nguji migrasi
# tambahan buat database yang tabelnya UDAH ADA dari SEBELUM perbaikan
# ini (FK versi lama, tanpa ON DELETE SET NULL).
# --------------------------------------------------------------------------


def _actor_fk_ondelete(path):
    """`ondelete` FK `caregiver_audit_events.actor_user_id -> users.id` di `path` — None kalau nggak ada FK/tabelnya sama sekali."""
    engine = create_engine(f"sqlite:///{path}")
    try:
        inspector = sa_inspect(engine)
        if "caregiver_audit_events" not in inspector.get_table_names():
            return None
        for fk in inspector.get_foreign_keys("caregiver_audit_events"):
            if fk.get("constrained_columns") == ["actor_user_id"]:
                return (fk.get("options") or {}).get("ondelete")
        return None
    finally:
        engine.dispose()


def _seed_schema_with_old_style_audit_fk(path):
    """
    Simulasi database yang UDAH PERNAH migrasi tabel caregiver_audit_events
    SEBELUM Issue 2 diperbaiki — tabelnya udah ada, FK `actor_user_id`-nya
    TANPA `ON DELETE SET NULL` (skema lama), diisi 1 baris event "asli"
    buat mbuktiin migrasi FK ini TIDAK PERNAH kehilangan baris yang udah
    ada.
    """
    engine = create_engine(f"sqlite:///{path}")
    tables_to_create = [t for t in db.metadata.sorted_tables if t.name != "caregiver_audit_events"]
    db.metadata.create_all(bind=engine, tables=tables_to_create)

    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE caregiver_audit_events (
                id INTEGER NOT NULL PRIMARY KEY,
                child_id INTEGER NOT NULL,
                actor_user_id INTEGER,
                action VARCHAR(10) NOT NULL,
                entity_type VARCHAR(30) NOT NULL,
                entity_id INTEGER NOT NULL,
                changed_fields_json JSON,
                recorded_at DATETIME,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(actor_user_id) REFERENCES users (id),
                FOREIGN KEY(child_id) REFERENCES children (id)
            )
            """
        ))
        conn.execute(text("CREATE INDEX ix_caregiver_audit_events_child_id ON caregiver_audit_events (child_id)"))
        conn.execute(text("CREATE INDEX ix_caregiver_audit_events_actor_user_id ON caregiver_audit_events (actor_user_id)"))
        conn.execute(text("CREATE INDEX ix_caregiver_audit_events_created_at ON caregiver_audit_events (created_at)"))

        conn.execute(
            db.metadata.tables["users"].insert(),
            {
                "name": "Legacy Actor", "email": "legacy-fk-actor@example.com",
                "password_hash": "not-a-real-hash", "telegram_chat_id": None,
                "created_at": datetime(2024, 1, 1),
            },
        )
        conn.execute(
            db.metadata.tables["children"].insert(),
            {
                "user_id": 1, "name": "Legacy FK Child", "nickname": None,
                "birth_date": date(2024, 1, 1), "gender": "L",
                "birth_weight_kg": None, "birth_height_cm": None, "photo_filename": None,
                "created_at": datetime(2024, 1, 1),
            },
        )
        conn.execute(
            db.metadata.tables["child_caregivers"].insert(),
            {"child_id": 1, "user_id": 1, "role": "owner", "created_at": datetime(2024, 1, 1)},
        )
        conn.execute(text(
            """
            INSERT INTO caregiver_audit_events
                (child_id, actor_user_id, action, entity_type, entity_id, changed_fields_json, recorded_at, created_at)
            VALUES
                (1, 1, 'create', 'feeding_log', 1, NULL, '2024-01-02 08:00:00', '2024-01-02 08:00:05')
            """
        ))
    engine.dispose()


def test_migration_upgrades_actor_fk_to_on_delete_set_null(temp_db_path, monkeypatch):
    _seed_schema_with_old_style_audit_fk(temp_db_path)
    assert _actor_fk_ondelete(temp_db_path) is None  # skema lama, belum ada ON DELETE SET NULL

    _run_migrate_against(temp_db_path, monkeypatch)

    assert (_actor_fk_ondelete(temp_db_path) or "").upper() == "SET NULL"


def test_fk_migration_preserves_the_existing_audit_row_exactly(temp_db_path, monkeypatch):
    _seed_schema_with_old_style_audit_fk(temp_db_path)
    _run_migrate_against(temp_db_path, monkeypatch)

    conn = sqlite3.connect(temp_db_path)
    try:
        row = conn.execute(
            "SELECT child_id, actor_user_id, action, entity_type, entity_id, changed_fields_json, "
            "recorded_at, created_at FROM caregiver_audit_events;"
        ).fetchall()
        assert row == [
            (1, 1, "create", "feeding_log", 1, None, "2024-01-02 08:00:00", "2024-01-02 08:00:05"),
        ]
    finally:
        conn.close()


def test_fk_migration_preserves_expected_indexes(temp_db_path, monkeypatch):
    _seed_schema_with_old_style_audit_fk(temp_db_path)
    _run_migrate_against(temp_db_path, monkeypatch)

    indexed = _indexed_columns(temp_db_path, "caregiver_audit_events")
    assert "child_id" in indexed
    assert "actor_user_id" in indexed
    assert "created_at" in indexed


def test_rerunning_the_fk_migration_twice_is_safe(temp_db_path, monkeypatch):
    _seed_schema_with_old_style_audit_fk(temp_db_path)
    _run_migrate_against(temp_db_path, monkeypatch)
    _run_migrate_against(temp_db_path, monkeypatch)  # kedua kalinya HARUS no-op, bukan error

    assert (_actor_fk_ondelete(temp_db_path) or "").upper() == "SET NULL"
    conn = sqlite3.connect(temp_db_path)
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM caregiver_audit_events;").fetchone()
        assert count == 1  # baris lama TETAP cuma 1 (nggak didobelin, nggak ilang)
    finally:
        conn.close()


def test_fresh_database_already_has_the_correct_actor_fk_without_any_extra_migration_step(temp_db_path, monkeypatch):
    """Database yang BELUM PERNAH punya caregiver_audit_events sama sekali (skenario paling umum) langsung dapet FK yang benar dari db.create_all(), tanpa perlu migrasi FK tambahan."""
    _seed_pre_audit_trail_schema(temp_db_path)
    assert _actor_fk_ondelete(temp_db_path) is None  # tabelnya belum ada sama sekali

    _run_migrate_against(temp_db_path, monkeypatch)

    assert (_actor_fk_ondelete(temp_db_path) or "").upper() == "SET NULL"
