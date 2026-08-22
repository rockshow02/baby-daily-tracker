"""
Test buat scripts/backup_database.py, scripts/restore_database.py, dan
scripts/db_backup_common.py.

SEMUA test di sini pakai file SQLite SEMENTARA (tempfile.mkdtemp()) yang
dibikin/dihapus per-test — TIDAK ADA satupun test yang membaca, menimpa,
atau menghapus instance/tracker.db yang beneran dipakai dev/staging/
production (lihat test_25_* di paling bawah buat penegasan eksplisitnya).
"""

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BACKEND_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from app import create_app  # noqa: E402

import db_backup_common as dbc  # noqa: E402
import backup_database  # noqa: E402
import restore_database  # noqa: E402


REAL_INSTANCE_DB = Path(BACKEND_DIR) / "instance" / "tracker.db"


# --------------------------------------------------------------------------
# fixtures — semuanya di tempfile.mkdtemp(), nggak pernah di dalam repo
# --------------------------------------------------------------------------


@pytest.fixture
def workdir():
    d = tempfile.mkdtemp(prefix="dbbackup-test-")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def source_db_path(workdir):
    path = workdir / "source.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users (name) VALUES ('alice')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def backup_dir(workdir):
    d = workdir / "backups"
    d.mkdir()
    return d


def make_app_for(db_path):
    """create_app() nunjuk ke file SQLite sementara — POLA YANG SAMA kayak
    tests/test_concurrency.py:file_db_app, dipakai di sini juga buat
    mastiin resolve_active_sqlite_path() beneran baca dari config app,
    bukan hardcode."""
    return create_app(config_overrides={"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"})


# --------------------------------------------------------------------------
# 1-8: mekanisme backup inti (db_backup_common.create_backup)
# --------------------------------------------------------------------------


def test_1_successful_backup_of_valid_sqlite_database(source_db_path, backup_dir):
    result = dbc.create_backup(source_db_path, backup_dir, "staging")
    assert result.path.is_file()
    assert result.integrity_ok is True
    assert result.source_path == source_db_path


def test_2_backup_remains_consistent_while_source_connection_open(source_db_path, backup_dir):
    # koneksi lain ke source TETAP kebuka selama backup dijalankan — meniru
    # aplikasi web yang masih hidup pas backup dipicu manual
    keep_open = sqlite3.connect(str(source_db_path))
    try:
        result = dbc.create_backup(source_db_path, backup_dir, "staging")
        assert result.integrity_ok is True

        conn = sqlite3.connect(str(result.path))
        rows = conn.execute("SELECT name FROM users").fetchall()
        conn.close()
        assert rows == [("alice",)]
    finally:
        keep_open.close()


def test_3_source_database_remains_unchanged(source_db_path, backup_dir):
    before_hash = dbc.sha256_of_file(source_db_path)
    dbc.create_backup(source_db_path, backup_dir, "staging")
    after_hash = dbc.sha256_of_file(source_db_path)
    assert before_hash == after_hash


def test_4_integrity_check_succeeds(source_db_path, backup_dir):
    result = dbc.create_backup(source_db_path, backup_dir, "staging")
    ok, detail = dbc.check_integrity(result.path)
    assert ok is True
    assert detail == "ok"


def test_5_backup_filename_correctly_timestamped(source_db_path, backup_dir):
    result = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-120000")
    assert result.filename == "tracker-staging-20260101-120000.db"
    assert (backup_dir / "tracker-staging-20260101-120000.db").is_file()
    parsed = dbc.parse_backup_filename(result.filename)
    assert parsed == {"environment": "staging", "timestamp": "20260101-120000"}


def test_6_environment_label_is_sanitized(source_db_path, backup_dir):
    assert dbc.sanitize_environment_label("Staging") == "staging"
    assert dbc.sanitize_environment_label("  production  ") == "production"

    for bad in ["staging/../etc", "has space", "", "../../etc/passwd", "a/b", "UP%"]:
        with pytest.raises(dbc.BackupError):
            dbc.sanitize_environment_label(bad)

    # create_backup sendiri juga mengaplikasikan sanitasi ini (bukan cuma dites terpisah)
    with pytest.raises(dbc.BackupError):
        dbc.create_backup(source_db_path, backup_dir, "staging/../evil")


def test_7_existing_backup_file_is_not_overwritten(source_db_path, backup_dir):
    dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-120000")
    original_hash = dbc.sha256_of_file(backup_dir / "tracker-staging-20260101-120000.db")

    # ubah source-nya biar KALAU sampai ke-timpa, isinya bakal beda
    conn = sqlite3.connect(str(source_db_path))
    conn.execute("INSERT INTO users (name) VALUES ('bob')")
    conn.commit()
    conn.close()

    with pytest.raises(dbc.BackupError):
        dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-120000")

    # file backup pertama TETAP utuh, nggak ke-timpa
    assert dbc.sha256_of_file(backup_dir / "tracker-staging-20260101-120000.db") == original_hash


def test_8_failure_removes_only_the_incomplete_temp_file(source_db_path, backup_dir, monkeypatch):
    # simulasikan integrity check GAGAL — create_backup harus batalin
    # sebelum rename final, dan cuma file .tmp-* yang boleh kehapus
    monkeypatch.setattr(dbc, "check_integrity", lambda p: (False, "simulated corruption"))

    with pytest.raises(dbc.BackupError):
        dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-130000")

    assert list(backup_dir.iterdir()) == []  # nggak ada file .db ATAU .tmp-* yang ketinggalan
    assert source_db_path.is_file()  # source tetap ada & tidak disentuh


# --------------------------------------------------------------------------
# 9-12: validasi resolve_active_sqlite_path / resolve_backup_dir
# --------------------------------------------------------------------------


def test_9_missing_source_database_file_is_rejected(workdir):
    target = workdir / "will_be_deleted.db"
    app = make_app_for(target)
    assert target.is_file()  # db.create_all() bikin filenya duluan

    with app.app_context():
        from extensions import db as _db

        _db.engine.dispose()  # lepas handle file-nya dulu (wajib di Windows sebelum unlink)
    target.unlink()  # simulasikan file ilang SEBELUM backup dijalankan

    with pytest.raises(dbc.BackupError, match="nggak ditemukan"):
        dbc.resolve_active_sqlite_path(app)


def test_10_in_memory_sqlite_is_rejected():
    app = create_app(config_overrides={"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with pytest.raises(dbc.BackupError, match="in-memory"):
        dbc.resolve_active_sqlite_path(app)


def test_11_non_sqlite_configuration_is_rejected():
    # dites lewat helper PURE-nya (bukan create_app beneran) — nggak butuh
    # driver postgres/mysql ke-install cuma buat nguji cabang penolakan ini
    with pytest.raises(dbc.BackupError, match="bukan SQLite"):
        dbc.resolve_sqlite_path_from_url("postgresql", "somedb")


def test_12_backup_directory_is_created_safely(source_db_path, workdir):
    nested = workdir / "does" / "not" / "exist" / "yet"
    assert not nested.exists()

    result = dbc.create_backup(source_db_path, nested, "staging")

    assert nested.is_dir()
    # .resolve() di kedua sisi — di Windows, path yang sama bisa punya 2
    # representasi string beda (short 8.3 name vs long name)
    assert result.path.parent.resolve() == nested.resolve()


# --------------------------------------------------------------------------
# 13-16: list / verify
# --------------------------------------------------------------------------


def test_13_list_mode_ignores_unrelated_files(source_db_path, backup_dir):
    dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-120000")

    (backup_dir / "readme.txt").write_text("bukan backup")
    (backup_dir / "random.db").write_bytes(b"not a real filename pattern match anyway")
    (backup_dir / "somedir").mkdir()

    entries = dbc.list_backups(backup_dir)

    assert len(entries) == 1
    assert entries[0]["filename"] == "tracker-staging-20260101-120000.db"


def test_14_verify_mode_detects_a_corrupted_database(source_db_path, backup_dir):
    result = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-120000")

    with open(result.path, "r+b") as f:
        f.seek(100)
        f.write(b"\xff" * 200)

    verify_result = dbc.verify_backup(result.path, backup_dir)
    assert verify_result.integrity_ok is False


def test_15_verify_mode_rejects_path_outside_backup_directory(source_db_path, backup_dir, workdir):
    outside_dir = workdir / "elsewhere"
    outside_dir.mkdir()
    outside_backup = dbc.create_backup(source_db_path, outside_dir, "staging", timestamp="20260101-120000")

    with pytest.raises(dbc.BackupError, match="di dalam folder backup"):
        dbc.verify_backup(outside_backup.path, backup_dir)


def test_16_escaping_symlinks_are_rejected_where_supported(source_db_path, backup_dir, workdir):
    outside_dir = workdir / "elsewhere"
    outside_dir.mkdir()
    outside_backup = dbc.create_backup(source_db_path, outside_dir, "staging", timestamp="20260101-140000")

    link_path = backup_dir / "tracker-staging-20260101-150000.db"
    try:
        os.symlink(outside_backup.path, link_path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink nggak didukung/diizinkan di environment ini")

    # --list HARUS mengabaikan symlink yang nunjuk keluar backup_dir
    entries = dbc.list_backups(backup_dir)
    assert entries == []

    # --verify langsung ke symlink itu juga harus DITOLAK
    with pytest.raises(dbc.BackupError, match="di dalam folder backup"):
        dbc.verify_backup(link_path, backup_dir)


# --------------------------------------------------------------------------
# 17-22: restore
# --------------------------------------------------------------------------


def make_restore_args(**overrides):
    defaults = dict(
        backup=None,
        environment="staging",
        backup_dir=None,
        allow_outside_backup_dir=False,
        override_environment_mismatch=False,
        confirm_environment=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture
def restore_env(workdir, backup_dir):
    """Database aktif (temp file) + Flask app yang nunjuk ke situ + 1 backup valid buat direstore."""
    active_db_path = workdir / "active.db"
    conn = sqlite3.connect(str(active_db_path))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users (name) VALUES ('original')")
    conn.commit()
    conn.close()

    app = make_app_for(active_db_path)

    backup_result = dbc.create_backup(active_db_path, backup_dir, "staging", timestamp="20260101-090000")

    # ubah active db SETELAH backup dibikin, biar restore beneran keliatan efeknya
    conn = sqlite3.connect(str(active_db_path))
    conn.execute("INSERT INTO users (name) VALUES ('modified-after-backup')")
    conn.commit()
    conn.close()

    return {
        "app": app,
        "active_db_path": active_db_path,
        "backup_dir": backup_dir,
        "backup_path": backup_result.path,
    }


_restore_call_counter = {"n": 0}


def run_restore(monkeypatch, env, **arg_overrides):
    monkeypatch.setattr(restore_database, "create_app", lambda: env["app"])
    # safety-backup di dalam restore() makein timestamp granularitas detik
    # buat nama filenya — kalau 1 test manggil run_restore() lebih dari
    # sekali (mis. nyoba confirm SALAH dulu, baru BENAR), 2 panggilan bisa
    # kejadian di detik yang SAMA persis dan filenya tabrakan (yang justru
    # BENAR — itu proteksi "jangan overwrite" bekerja). Biar test lain bisa
    # jalan tanpa nunggu 1 detik beneran, kasih timestamp unik per panggilan.
    _restore_call_counter["n"] += 1
    unique_ts = f"19000101-{_restore_call_counter['n']:06d}"
    monkeypatch.setattr(dbc, "timestamp_for_filename", lambda: unique_ts)
    args = make_restore_args(backup=str(env["backup_path"]), backup_dir=str(env["backup_dir"]), **arg_overrides)
    return restore_database.restore(args)


def test_17_restore_requires_exact_confirmation(monkeypatch, restore_env):
    # ketikan yang SALAH (bukan cuma beda kapital, beneran salah) -> dibatalkan
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
    code = run_restore(monkeypatch, restore_env)
    assert code != 0

    conn = sqlite3.connect(str(restore_env["active_db_path"]))
    rows = conn.execute("SELECT name FROM users ORDER BY id").fetchall()
    conn.close()
    assert rows == [("original",), ("modified-after-backup",)]  # TIDAK berubah

    # ketikan yang PERSIS BENAR -> lanjut
    monkeypatch.setattr("builtins.input", lambda prompt="": "RESTORE staging")
    code2 = run_restore(monkeypatch, restore_env)
    assert code2 == 0

    conn = sqlite3.connect(str(restore_env["active_db_path"]))
    rows2 = conn.execute("SELECT name FROM users").fetchall()
    conn.close()
    assert rows2 == [("original",)]  # sekarang berubah, sesuai isi backup


def test_18_restore_rejects_environment_mismatch(monkeypatch, restore_env):
    code = run_restore(monkeypatch, restore_env, environment="production", confirm_environment="production")
    assert code != 0

    conn = sqlite3.connect(str(restore_env["active_db_path"]))
    rows = conn.execute("SELECT name FROM users ORDER BY id").fetchall()
    conn.close()
    assert rows == [("original",), ("modified-after-backup",)]  # TIDAK berubah — backup-nya "staging", diminta "production"


def test_19_restore_creates_a_safety_backup_first(monkeypatch, restore_env):
    before = {e["filename"] for e in dbc.list_backups(restore_env["backup_dir"])}

    code = run_restore(monkeypatch, restore_env, confirm_environment="staging")
    assert code == 0

    after = {e["filename"] for e in dbc.list_backups(restore_env["backup_dir"])}
    new_files = after - before
    assert len(new_files) == 1  # 1 safety backup baru, isinya kondisi SEBELUM restore

    safety_path = restore_env["backup_dir"] / next(iter(new_files))
    conn = sqlite3.connect(str(safety_path))
    rows = conn.execute("SELECT name FROM users ORDER BY id").fetchall()
    conn.close()
    assert rows == [("original",), ("modified-after-backup",)]  # safety backup = kondisi SEBELUM restore


def test_20_restore_replaces_target_with_selected_backup(monkeypatch, restore_env):
    code = run_restore(monkeypatch, restore_env, confirm_environment="staging")
    assert code == 0

    conn = sqlite3.connect(str(restore_env["active_db_path"]))
    rows = conn.execute("SELECT name FROM users").fetchall()
    conn.close()
    assert rows == [("original",)]  # persis isi backup yang dipilih, bukan yang "modified"


def test_21_restore_verification_succeeds_afterward(monkeypatch, restore_env):
    code = run_restore(monkeypatch, restore_env, confirm_environment="staging")
    assert code == 0

    ok, detail = dbc.check_integrity(restore_env["active_db_path"])
    assert ok is True
    assert detail == "ok"


def test_22_failed_restore_preserves_safety_backup_and_leaves_original_untouched(monkeypatch, restore_env):
    # os.replace() dipakai 2x dalam 1 alur restore: sekali di dalam
    # create_backup() (buat nge-rename tmp -> final SAFETY backup), dan
    # sekali lagi buat nge-replace database AKTIF dengan hasil restore.
    # Cuma yang KEDUA (target = active_db_path) yang harus gagal di sini —
    # kalau yang PERTAMA ikut digagalin, safety backup-nya sendiri nggak
    # akan pernah kebentuk, dan test ini nggak bener-bener nguji skenario
    # "replace ke database aktif gagal, tapi safety backup-nya tetap ada".
    real_replace = os.replace
    # .resolve() — restore.py sendiri baca active_db_path lewat
    # resolve_active_sqlite_path() (yang meng-.resolve()-kan path-nya),
    # jadi perbandingan string di sini juga harus dalam bentuk resolved
    # yang sama (di Windows, short 8.3 name vs long name beda representasi)
    active_path_str = str(restore_env["active_db_path"].resolve())

    def selective_boom(src, dst):
        if str(dst) == active_path_str:
            raise OSError("simulated disk failure during replace")
        return real_replace(src, dst)

    monkeypatch.setattr(restore_database.os, "replace", selective_boom)

    code = run_restore(monkeypatch, restore_env, confirm_environment="staging")
    assert code != 0

    # database aktif TIDAK berubah (os.replace gagal SEBELUM benar-benar menimpa)
    conn = sqlite3.connect(str(restore_env["active_db_path"]))
    rows = conn.execute("SELECT name FROM users ORDER BY id").fetchall()
    conn.close()
    assert rows == [("original",), ("modified-after-backup",)]

    # safety backup yang dibikin SEBELUM percobaan replace tetap ada
    entries = dbc.list_backups(restore_env["backup_dir"])
    assert len(entries) == 2  # backup asli + safety backup, keduanya tetap ada


# --------------------------------------------------------------------------
# 23-24: prune
# --------------------------------------------------------------------------


def _seed_backups(source_db_path, backup_dir, timestamps, environment="staging"):
    for ts in timestamps:
        dbc.create_backup(source_db_path, backup_dir, environment, timestamp=ts)


def test_23_prune_is_dry_run_by_default(source_db_path, backup_dir):
    _seed_backups(source_db_path, backup_dir, ["20260101-090000", "20260101-100000", "20260101-110000"])

    result = dbc.prune_backups(backup_dir, keep=1, apply=False)

    assert len(result["to_delete"]) == 2
    # dry-run -> nggak ada satupun file yang beneran kehapus
    assert len(dbc.list_backups(backup_dir)) == 3


def test_24_prune_never_deletes_the_newest_valid_backup(source_db_path, backup_dir):
    _seed_backups(source_db_path, backup_dir, ["20260101-090000", "20260101-100000", "20260101-110000"])

    result = dbc.prune_backups(backup_dir, keep=0, apply=True)  # keep=0, kasus ekstrem

    remaining = {e["filename"] for e in dbc.list_backups(backup_dir)}
    assert remaining == {"tracker-staging-20260101-110000.db"}  # TERBARU tetap ada walau keep=0
    assert len(result["to_delete"]) == 2


# --------------------------------------------------------------------------
# 25: penegasan eksplisit — nggak ada test yang nyentuh instance/tracker.db asli
# --------------------------------------------------------------------------


def test_25_never_touches_the_real_project_database(workdir):
    app = make_app_for(workdir / "isolated.db")
    resolved = dbc.resolve_active_sqlite_path(app)

    # path yang di-backup/restore di seluruh test file ini SELALU di bawah
    # tempfile.mkdtemp() — nggak pernah sama dengan file database asli
    # proyek ini, dan nggak pernah di dalam repo sama sekali
    # (.resolve() di kedua sisi — di Windows, tempfile.mkdtemp() bisa balikin
    # bentuk short 8.3 name yang beda representasi string-nya dari long name)
    assert str(workdir.resolve()) in str(resolved)
    assert not str(resolved).startswith(str(Path(BACKEND_DIR).resolve()))
    if REAL_INSTANCE_DB.exists():
        assert resolved != REAL_INSTANCE_DB.resolve()
