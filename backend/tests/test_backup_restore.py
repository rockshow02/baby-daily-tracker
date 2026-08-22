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

    assert result["applied"] is False
    assert result["deleted"] == []  # 19/20. dry-run -> "deleted" HARUS kosong, bukan cuma "to_delete"
    assert len(result["to_delete"]) == 2
    assert len(result["existing"]) == 3  # 19. existing selalu mencerminkan SEMUA backup yang beneran ada
    assert len(result["remaining_after_apply"]) == 1  # 20. proyeksi sisa KALAU seandainya di-apply

    # dry-run -> nggak ada satupun file yang beneran kehapus di disk
    assert len(dbc.list_backups(backup_dir)) == 3


def test_24_prune_never_deletes_the_newest_valid_backup(source_db_path, backup_dir):
    _seed_backups(source_db_path, backup_dir, ["20260101-090000", "20260101-100000", "20260101-110000"])

    # keep=MIN_KEEP (1) — kasus paling ekstrem yang masih valid sejak keep
    # sekarang wajib >= 1 (lihat test_prune_keep_below_minimum_is_rejected)
    result = dbc.prune_backups(backup_dir, keep=dbc.MIN_KEEP, apply=True, active_db_path=source_db_path)

    remaining = {e["filename"] for e in dbc.list_backups(backup_dir)}
    assert remaining == {"tracker-staging-20260101-110000.db"}  # TERBARU tetap ada walau keep di batas minimal
    assert len(result["to_delete"]) == 2
    assert len(result["deleted"]) == 2
    assert result["aborted"] is False


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


# --------------------------------------------------------------------------
# validate_backup_directory — corrective fix for the broad-directory /
# unsafe-prune safety issue (db_backup_common.validate_backup_directory)
# --------------------------------------------------------------------------


def _symlinks_supported(workdir):
    """Cek dukungan symlink SEKALI di awal test (bukan nunggu ketauan gagal
    di tengah-tengah setup yang lebih rumit) — di Windows tanpa privilese
    elevated, os.symlink() nolak bikin symlink sama sekali."""
    target = workdir / "symlink-capability-target"
    link = workdir / "symlink-capability-check"
    target.write_text("x")
    try:
        os.symlink(target, link)
        link.unlink()
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        target.unlink(missing_ok=True)


def test_backupdir_1_filesystem_root_is_rejected():
    root = Path(BACKEND_DIR).anchor  # "/" di POSIX, drive root (mis. "Z:\\") di Windows
    with pytest.raises(dbc.BackupError, match="root filesystem"):
        dbc.validate_backup_directory(root)


def test_backupdir_2_windows_drive_root_is_rejected_where_applicable():
    if os.name != "nt":
        pytest.skip("cuma relevan di Windows")
    drive_root = Path(BACKEND_DIR).drive + "\\"
    with pytest.raises(dbc.BackupError, match="root filesystem"):
        dbc.validate_backup_directory(drive_root)


def test_backupdir_3_home_directory_itself_is_rejected():
    with pytest.raises(dbc.BackupError, match="home directory"):
        dbc.validate_backup_directory(str(Path.home()))


def test_backupdir_4_repository_root_is_rejected():
    with pytest.raises(dbc.BackupError, match="root repository"):
        dbc.validate_backup_directory(str(dbc.REPO_ROOT))


def test_backupdir_5_backend_root_is_rejected():
    with pytest.raises(dbc.BackupError, match="root folder backend"):
        dbc.validate_backup_directory(str(dbc.BACKEND_DIR))


def test_backupdir_6_backend_instance_directory_is_rejected():
    with pytest.raises(dbc.BackupError, match="instance"):
        dbc.validate_backup_directory(str(dbc.BACKEND_DIR / "instance"))


def test_backupdir_7_active_database_parent_directory_is_rejected(workdir):
    active_db = workdir / "active.db"
    active_db.write_bytes(b"")
    with pytest.raises(dbc.BackupError, match="folder induk database aktif"):
        dbc.validate_backup_directory(str(workdir), active_db_path=active_db)


def test_backupdir_8_active_database_file_itself_is_rejected(workdir):
    active_db = workdir / "active.db"
    active_db.write_bytes(b"")
    with pytest.raises(dbc.BackupError, match="database aktif itu sendiri"):
        dbc.validate_backup_directory(str(active_db), active_db_path=active_db)


def test_backupdir_9_symlink_resolving_to_forbidden_directory_is_rejected(workdir):
    if not _symlinks_supported(workdir):
        pytest.skip("symlink nggak didukung/diizinkan di environment ini")

    link_path = workdir / "link-to-home"
    os.symlink(Path.home(), link_path, target_is_directory=True)

    with pytest.raises(dbc.BackupError, match="home directory"):
        dbc.validate_backup_directory(str(link_path))


def test_backupdir_10_unexpanded_dollar_home_is_rejected():
    with pytest.raises(dbc.BackupError, match="placeholder"):
        dbc.validate_backup_directory("$HOME/database-backups")


def test_backupdir_11_unexpanded_braced_dollar_home_is_rejected():
    with pytest.raises(dbc.BackupError, match="placeholder"):
        dbc.validate_backup_directory("${HOME}/database-backups")


def test_backupdir_12_unexpanded_userprofile_percent_is_rejected():
    with pytest.raises(dbc.BackupError, match="placeholder"):
        dbc.validate_backup_directory("%USERPROFILE%\\database-backups")


def test_backupdir_13_default_database_backups_remains_accepted():
    resolved = dbc.validate_backup_directory(str(dbc.DEFAULT_BACKUP_DIR))
    assert resolved == Path.home().resolve() / "database-backups"


def test_backupdir_14_valid_nested_dedicated_directory_remains_accepted():
    resolved = dbc.validate_backup_directory(str(dbc.DEFAULT_BACKUP_DIR / "staging"))
    assert resolved == Path.home().resolve() / "database-backups" / "staging"


def test_backupdir_15_cli_rejects_negative_keep():
    # keep negatif ditolak SEBELUM create_app()/resolve_backup_dir() pernah
    # kepanggil (lihat run_prune) — aman dites di sini tanpa perlu override
    # database apa pun, karena nggak pernah sampai nyentuh app Flask.
    exit_code = backup_database.main(["--prune", "--keep", "-1"])
    assert exit_code != 0


def test_backupdir_16_prune_backups_rejects_negative_keep_directly(source_db_path, backup_dir):
    with pytest.raises(dbc.BackupError):
        dbc.prune_backups(backup_dir, keep=-1, apply=False)


def test_backupdir_17_keep_zero_is_rejected():
    with pytest.raises(dbc.BackupError):
        dbc.prune_backups(Path.home() / "irrelevant-nonexistent-dir", keep=0, apply=False)


def test_backupdir_18_dry_run_deletes_nothing(source_db_path, backup_dir):
    _seed_backups(source_db_path, backup_dir, ["20260101-090000", "20260101-100000", "20260101-110000"])

    result = dbc.prune_backups(backup_dir, keep=1, apply=False)

    assert result["applied"] is False
    assert result["deleted"] == []
    for f in ["tracker-staging-20260101-090000.db", "tracker-staging-20260101-100000.db", "tracker-staging-20260101-110000.db"]:
        assert (backup_dir / f).is_file()


def test_backupdir_19_dry_run_existing_contains_all_current_backups(source_db_path, backup_dir):
    _seed_backups(source_db_path, backup_dir, ["20260101-090000", "20260101-100000", "20260101-110000"])

    result = dbc.prune_backups(backup_dir, keep=1, apply=False)

    assert {e["filename"] for e in result["existing"]} == {
        "tracker-staging-20260101-090000.db",
        "tracker-staging-20260101-100000.db",
        "tracker-staging-20260101-110000.db",
    }


def test_backupdir_20_dry_run_remaining_after_apply_is_projected_correctly(source_db_path, backup_dir):
    _seed_backups(source_db_path, backup_dir, ["20260101-090000", "20260101-100000", "20260101-110000"])

    result = dbc.prune_backups(backup_dir, keep=2, apply=False)

    assert {e["filename"] for e in result["remaining_after_apply"]} == {
        "tracker-staging-20260101-100000.db",
        "tracker-staging-20260101-110000.db",
    }
    # proyeksi doang — disk belum berubah apa-apa
    assert len(dbc.list_backups(backup_dir)) == 3


def test_backupdir_21_apply_never_deletes_the_newest_backup(source_db_path, backup_dir):
    _seed_backups(source_db_path, backup_dir, ["20260101-090000", "20260101-100000", "20260101-110000"])

    result = dbc.prune_backups(backup_dir, keep=1, apply=True, active_db_path=source_db_path)

    assert result["aborted"] is False
    remaining = {e["filename"] for e in dbc.list_backups(backup_dir)}
    assert remaining == {"tracker-staging-20260101-110000.db"}
    assert {e["filename"] for e in result["deleted"]} == {
        "tracker-staging-20260101-090000.db",
        "tracker-staging-20260101-100000.db",
    }


def test_backupdir_22_candidate_replaced_by_symlink_before_deletion_aborts(source_db_path, backup_dir, workdir, monkeypatch):
    if not _symlinks_supported(workdir):
        pytest.skip("symlink nggak didukung/diizinkan di environment ini")

    r1 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-090000")
    r2 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-100000")  # newest, dilindungi

    outside_dir = workdir / "elsewhere"
    outside_dir.mkdir()
    elsewhere_file = outside_dir / "not-a-backup.db"
    elsewhere_file.write_bytes(b"whatever")

    real_list_backups = dbc.list_backups
    swapped = {"done": False}

    def fake_list_backups(bdir, **kwargs):
        # snapshot listing DULU (ini yang dipakai prune_backups buat nentuin
        # kandidat hapus) — BARU SETELAH ITU r1 diganti jadi symlink, meniru
        # perubahan yang kejadian ANTARA listing dan mulai penghapusan
        listing = real_list_backups(bdir, **kwargs)
        if not swapped["done"]:
            swapped["done"] = True
            r1.path.unlink()
            os.symlink(elsewhere_file, r1.path)
        return listing

    monkeypatch.setattr(dbc, "list_backups", fake_list_backups)

    result = dbc.prune_backups(backup_dir, keep=1, apply=True, active_db_path=source_db_path)

    assert result["aborted"] is True
    assert "symlink" in result["abort_reason"]
    assert r2.path.is_file()  # newest tetap utuh, nggak sempat disentuh


def test_backupdir_23_candidate_moved_outside_directory_before_deletion_aborts(source_db_path, backup_dir, workdir, monkeypatch):
    r1 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-090000")
    r2 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-100000")  # newest, dilindungi

    outside_dir = workdir / "elsewhere"
    outside_dir.mkdir()

    real_list_backups = dbc.list_backups
    moved = {"done": False}

    def fake_list_backups(bdir, **kwargs):
        listing = real_list_backups(bdir, **kwargs)
        if not moved["done"]:
            moved["done"] = True
            shutil.move(str(r1.path), str(outside_dir / r1.path.name))
        return listing

    monkeypatch.setattr(dbc, "list_backups", fake_list_backups)

    result = dbc.prune_backups(backup_dir, keep=1, apply=True, active_db_path=source_db_path)

    assert result["aborted"] is True
    assert r2.path.is_file()  # newest tetap utuh


def test_backupdir_24_unrelated_json_files_are_never_deleted(source_db_path, backup_dir):
    r1 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-090000")
    r2 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-100000")  # newest

    unrelated_json = backup_dir / "unrelated-notes.json"
    unrelated_json.write_text('{"not": "a backup metadata file"}')

    dbc.prune_backups(backup_dir, keep=1, apply=True, active_db_path=source_db_path)

    assert unrelated_json.is_file()  # nggak ikut kehapus sama sekali
    assert not r1.metadata_path.exists()  # metadata backup yang DIHAPUS ikut kehapus
    assert r2.metadata_path.exists()


def test_backupdir_25_only_exact_adjacent_metadata_is_deleted(source_db_path, backup_dir):
    r1 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-090000")
    dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-100000")  # newest

    # file .json yang MIRIP tapi BUKAN metadata r1 (nama beda dikit)
    decoy = backup_dir / "tracker-staging-20260101-090000-decoy.db.json"
    decoy.write_text("{}")

    dbc.prune_backups(backup_dir, keep=1, apply=True, active_db_path=source_db_path)

    assert not r1.metadata_path.exists()
    assert decoy.is_file()  # nama nggak PERSIS cocok -> nggak disentuh


def test_backupdir_26_partial_deletion_failure_is_reported_accurately(source_db_path, backup_dir, monkeypatch):
    r1 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-090000")
    r2 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-100000")
    r3 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-110000")  # newest, dilindungi

    # urutan proses (descending timestamp, newest dikecualikan): r2 duluan, baru r1
    real_unlink = Path.unlink

    def selective_boom(self, *a, **k):
        if self == r1.path:
            raise OSError("simulated failure deleting r1")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", selective_boom)

    result = dbc.prune_backups(backup_dir, keep=1, apply=True, active_db_path=source_db_path)

    assert result["applied"] is True
    assert result["aborted"] is True
    assert {e["filename"] for e in result["deleted"]} == {"tracker-staging-20260101-100000.db"}  # r2 SUDAH kehapus
    assert not r2.path.exists()  # beneran hilang dari disk
    assert r1.path.is_file()  # r1 GAGAL dihapus, tapi TETAP ada (bukan setengah-hapus)
    assert r3.path.is_file()  # newest nggak pernah disentuh


def test_backupdir_28_no_test_touches_the_real_instance_database():
    # penegasan eksplisit KEDUA (di luar test_25) khusus buat rangkaian test
    # validate_backup_directory di atas — semuanya beroperasi di
    # tempfile.mkdtemp() lewat fixture workdir/backup_dir/source_db_path,
    # nggak pernah menyentuh REAL_INSTANCE_DB.
    assert REAL_INSTANCE_DB == Path(BACKEND_DIR) / "instance" / "tracker.db"


def _raise(exc):
    """Helper: fungsi yang manggilnya SELALU raise `exc` — dipakai buat monkeypatch create_app()/dst di test."""

    def _inner(*args, **kwargs):
        raise exc

    return _inner


# --------------------------------------------------------------------------
# Issue 1 — kegagalan hapus metadata SETELAH .db-nya berhasil dihapus harus
# dilaporkan akurat: backup TETAP tercatat "deleted", TIDAK masuk
# remaining_after_apply, dan pruning berikutnya berhenti (nggak lanjut
# nyoba kandidat lain).
# --------------------------------------------------------------------------


def test_metaf_1to10_backup_deleted_but_metadata_cleanup_fails(source_db_path, backup_dir, monkeypatch):
    r1 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-090000")
    r2 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-100000")  # newest, dilindungi

    real_unlink = Path.unlink

    def selective_boom(self, *a, **k):
        # 2. metadata .json PERSIS punya r1 gagal dihapus (OSError) — file
        # .db-nya sendiri (dan file lain mana pun) tetap dihapus normal
        if self == r1.metadata_path:
            raise OSError("simulated metadata deletion failure")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", selective_boom)

    result = dbc.prune_backups(backup_dir, keep=1, apply=True, active_db_path=source_db_path)

    # 3. applied=True
    assert result["applied"] is True
    # 4. aborted=True
    assert result["aborted"] is True
    # 5. backup (r1) ADA di deleted, walau metadata-nya gagal dihapus
    assert {e["filename"] for e in result["deleted"]} == {r1.filename}
    # 6. r1 TIDAK ada di remaining_after_apply
    remaining_names = {e["filename"] for e in result["remaining_after_apply"]}
    assert r1.filename not in remaining_names
    # 7. file .db r1 beneran nggak ada lagi di disk
    assert not r1.path.exists()
    # 8. file .db.json r1 MASIH ada (gagal dihapus, jadi yatim di disk)
    assert r1.metadata_path.exists()
    # 9. kandidat lain (r2, walau di sini cuma "newest" yang dilindungi) nggak disentuh
    assert r2.path.is_file()
    assert r2.metadata_path.exists()
    # 10. abort_reason menjelaskan JELAS ini kegagalan cleanup metadata (bukan gagal hapus .db)
    assert "metadata" in result["abort_reason"].lower()
    assert r1.filename in result["abort_reason"]
    # metadata_delete_failures — cuma path & pesan, nggak ada isi data
    assert len(result["metadata_delete_failures"]) == 1
    failure = result["metadata_delete_failures"][0]
    assert failure["backup_filename"] == r1.filename
    assert failure["metadata_path"] == str(r1.metadata_path)
    assert "error" in failure


def test_metaf_9_13_earlier_successful_deletions_remain_accurate_and_later_candidates_untouched(
    source_db_path, backup_dir, monkeypatch
):
    r1 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-090000")
    r2 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-100000")
    r3 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-110000")
    r4 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-120000")  # newest, dilindungi

    real_unlink = Path.unlink

    def selective_boom(self, *a, **k):
        if self == r2.metadata_path:
            raise OSError("simulated metadata deletion failure")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", selective_boom)

    # urutan proses (descending timestamp, newest r4 dikecualikan): r3, r2, r1
    result = dbc.prune_backups(backup_dir, keep=1, apply=True, active_db_path=source_db_path)

    assert result["aborted"] is True

    # r3 diproses DULUAN dan sukses PENUH (.db + metadata) — laporan "deleted" tetap akurat buat dia
    assert r3.filename in {e["filename"] for e in result["deleted"]}
    assert not r3.path.exists()
    assert not r3.metadata_path.exists()

    # r2 = kandidat yang metadata-nya gagal dihapus — .db-nya TETAP hilang, tercatat "deleted"
    assert r2.filename in {e["filename"] for e in result["deleted"]}
    assert not r2.path.exists()
    assert r2.metadata_path.exists()  # metadata yatim

    # r1 = kandidat SETELAHNYA (belum sempat diproses) — TIDAK disentuh sama sekali
    assert r1.path.is_file()
    assert r1.metadata_path.exists()
    assert r1.filename not in {e["filename"] for e in result["deleted"]}

    # r4 = terbaru, dilindungi, nggak pernah disentuh
    assert r4.path.is_file()
    assert r4.metadata_path.exists()


def test_metaf_11_12_cli_exits_nonzero_and_never_claims_deleted_backup_is_recoverable(
    source_db_path, backup_dir, monkeypatch, capsys
):
    r1 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-090000")
    dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-100000")  # newest

    real_unlink = Path.unlink

    def selective_boom(self, *a, **k):
        if self == r1.metadata_path:
            raise OSError("simulated metadata deletion failure")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", selective_boom)

    fake_app = make_app_for(source_db_path)
    monkeypatch.setattr(backup_database, "create_app", lambda: fake_app)

    exit_code = backup_database.main(["--prune", "--keep", "1", "--backup-dir", str(backup_dir), "--apply"])

    # 11. CLI keluar dengan kode nol-tidak-nol (non-zero)
    assert exit_code != 0

    out = capsys.readouterr().out
    # laporan menyebut lokasi metadata yatim secara eksplisit ("safe operational message")
    assert str(r1.metadata_path) in out
    # 12. CLI TIDAK PERNAH mengklaim backup yang sudah dihapus itu masih tersedia/bisa dipulihkan —
    # sebaliknya, secara eksplisit bilang backup-nya SUDAH terhapus PERMANEN
    assert "terhapus permanen" in out


def test_metaf_14_unrelated_json_files_remain_untouched_during_metadata_failure(source_db_path, backup_dir, monkeypatch):
    r1 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-090000")
    dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-100000")  # newest

    unrelated_json = backup_dir / "unrelated-notes.json"
    unrelated_json.write_text('{"not": "a backup metadata file"}')

    real_unlink = Path.unlink

    def selective_boom(self, *a, **k):
        if self == r1.metadata_path:
            raise OSError("simulated metadata deletion failure")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", selective_boom)

    dbc.prune_backups(backup_dir, keep=1, apply=True, active_db_path=source_db_path)

    assert unrelated_json.is_file()  # nggak ikut kesentuh sama sekali


# --------------------------------------------------------------------------
# Issue 2 — --prune --apply (destruktif) harus fail CLOSED kalau resolusi
# app Flask/database aktif gagal — bukan diam-diam lanjut tanpa proteksi
# folder induk/path database aktif.
# --------------------------------------------------------------------------


def test_faildb_1_cli_prune_apply_refuses_if_create_app_fails(backup_dir, monkeypatch):
    monkeypatch.setattr(backup_database, "create_app", _raise(RuntimeError("simulated create_app failure")))

    exit_code = backup_database.main(["--prune", "--keep", "1", "--backup-dir", str(backup_dir), "--apply"])

    assert exit_code != 0


def test_faildb_2_cli_prune_apply_refuses_if_active_db_resolution_fails(source_db_path, backup_dir, monkeypatch):
    fake_app = make_app_for(source_db_path)
    monkeypatch.setattr(backup_database, "create_app", lambda: fake_app)
    monkeypatch.setattr(
        backup_database, "resolve_active_sqlite_path", _raise(dbc.BackupError("simulated resolution failure"))
    )

    exit_code = backup_database.main(["--prune", "--keep", "1", "--backup-dir", str(backup_dir), "--apply"])

    assert exit_code != 0


def test_faildb_3_no_backup_deleted_in_either_failure(source_db_path, backup_dir, monkeypatch):
    r1 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-090000")
    r2 = dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-100000")

    monkeypatch.setattr(backup_database, "create_app", _raise(RuntimeError("simulated create_app failure")))
    backup_database.main(["--prune", "--keep", "1", "--backup-dir", str(backup_dir), "--apply"])

    assert r1.path.is_file()
    assert r2.path.is_file()


def test_faildb_4_error_message_states_active_db_could_not_be_verified(backup_dir, monkeypatch, capsys):
    monkeypatch.setattr(backup_database, "create_app", _raise(RuntimeError("simulated create_app failure")))

    backup_database.main(["--prune", "--keep", "1", "--backup-dir", str(backup_dir), "--apply"])

    captured = capsys.readouterr()
    combined = (captured.out + captured.err).lower()
    assert "database aktif" in combined


def test_faildb_5_prune_backups_apply_true_without_active_db_path_raises(backup_dir):
    with pytest.raises(dbc.BackupError):
        dbc.prune_backups(backup_dir, keep=1, apply=True, active_db_path=None)


def test_faildb_6_prune_backups_apply_false_without_active_db_path_is_safe_dry_run(source_db_path, backup_dir):
    _seed_backups(source_db_path, backup_dir, ["20260101-090000", "20260101-100000"])

    result = dbc.prune_backups(backup_dir, keep=1, apply=False, active_db_path=None)

    assert result["applied"] is False
    assert result["deleted"] == []
    assert len(dbc.list_backups(backup_dir)) == 2


def test_faildb_7_successful_apply_passes_active_db_path_through_all_layers(source_db_path, backup_dir, monkeypatch):
    _seed_backups(source_db_path, backup_dir, ["20260101-090000", "20260101-100000", "20260101-110000"])

    fake_app = make_app_for(source_db_path)
    monkeypatch.setattr(backup_database, "create_app", lambda: fake_app)

    exit_code = backup_database.main(["--prune", "--keep", "1", "--backup-dir", str(backup_dir), "--apply"])

    assert exit_code == 0
    remaining = {e["filename"] for e in dbc.list_backups(backup_dir)}
    assert remaining == {"tracker-staging-20260101-110000.db"}


def test_faildb_8_active_database_parent_directory_rejected_during_apply(source_db_path, workdir, monkeypatch):
    fake_app = make_app_for(source_db_path)
    monkeypatch.setattr(backup_database, "create_app", lambda: fake_app)

    # --backup-dir nunjuk ke folder INDUK database aktif (workdir langsung, bukan workdir/backups)
    exit_code = backup_database.main(["--prune", "--keep", "1", "--backup-dir", str(workdir), "--apply"])

    assert exit_code != 0


def test_faildb_9_active_database_file_itself_never_considered_backup_dir(source_db_path, monkeypatch):
    fake_app = make_app_for(source_db_path)
    monkeypatch.setattr(backup_database, "create_app", lambda: fake_app)

    exit_code = backup_database.main(["--prune", "--keep", "1", "--backup-dir", str(source_db_path), "--apply"])

    assert exit_code != 0


def test_faildb_10_list_and_verify_remain_functional_without_active_db_resolution(source_db_path, backup_dir, monkeypatch):
    dbc.create_backup(source_db_path, backup_dir, "staging", timestamp="20260101-090000")

    monkeypatch.setattr(backup_database, "create_app", _raise(RuntimeError("simulated create_app failure")))

    exit_code_list = backup_database.main(["--list", "--backup-dir", str(backup_dir)])
    assert exit_code_list == 0

    backup_path = backup_dir / "tracker-staging-20260101-090000.db"
    exit_code_verify = backup_database.main(["--verify", str(backup_path), "--backup-dir", str(backup_dir)])
    assert exit_code_verify == 0


def test_faildb_11_backup_cli_behavior_unchanged(source_db_path, backup_dir, monkeypatch):
    fake_app = make_app_for(source_db_path)
    monkeypatch.setattr(backup_database, "create_app", lambda: fake_app)

    exit_code = backup_database.main(["--environment", "staging", "--backup-dir", str(backup_dir)])

    assert exit_code == 0
    assert len(dbc.list_backups(backup_dir)) == 1
