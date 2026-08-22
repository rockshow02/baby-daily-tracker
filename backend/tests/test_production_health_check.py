"""
Test buat scripts/production_health_check.py.

SEMUA test di sini pakai file SQLite SEMENTARA (tempfile.mkdtemp()) dan
folder backup sementara (lewat env var DATABASE_BACKUP_DIR yang di-override
per-test) — TIDAK ADA satupun test yang membaca, menimpa, membuat, atau
menghapus instance/tracker.db yang beneran dipakai dev/staging/production
(lihat test_45_* di paling bawah buat penegasan eksplisitnya). Test yang
memanggil check_flask_app_creation()/phc.run() secara langsung tetap aman
karena tests/conftest.py udah nge-set FLASK_ENV=testing secara global buat
seluruh sesi pytest, jadi create_app() bare di dalamnya otomatis pakai
TestConfig (SQLite in-memory), bukan config Config/DevConfig yang nunjuk ke
instance/tracker.db asli.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections import namedtuple
from datetime import datetime, timedelta
from pathlib import Path

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BACKEND_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from app import create_app  # noqa: E402
from extensions import db  # noqa: E402

import db_backup_common as dbc  # noqa: E402
import production_health_check as phc  # noqa: E402


REAL_INSTANCE_DB = Path(BACKEND_DIR) / "instance" / "tracker.db"

_DiskUsage = namedtuple("_DiskUsage", "total used free")


# --------------------------------------------------------------------------
# fixtures — semuanya di tempfile.mkdtemp(), nggak pernah di dalam repo
# --------------------------------------------------------------------------


@pytest.fixture
def workdir():
    d = tempfile.mkdtemp(prefix="health-check-test-")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def backup_dir(workdir):
    d = workdir / "backups"
    d.mkdir()
    return d


def make_app(db_path):
    """create_app() nunjuk ke file SQLite sementara — pola yang sama kayak
    tests/test_backup_restore.py:make_app_for, biar checks yang butuh Flask
    app beneran (bukan mock) tetep jalan di atas DB yang aman dihapus."""
    return create_app(config_overrides={"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"})


# --------------------------------------------------------------------------
# 35: database sehat -> semua pengecekan lolos
# --------------------------------------------------------------------------


def test_35_healthy_temporary_database_passes_all_checks(workdir):
    db_path = workdir / "tracker.db"
    app = make_app(db_path)

    report = phc.Report(environment="test")
    result_path = phc.check_database_config_and_file(report, app)

    assert result_path is not None
    by_name = {r.name: r for r in report.results}
    for name in (
        "database_is_sqlite",
        "database_file_exists",
        "database_readable",
        "database_select_1",
        "database_quick_check",
        "database_file_size",
    ):
        assert by_name[name].status == phc.STATUS_OK, (name, by_name[name].detail)


# --------------------------------------------------------------------------
# 36: database hilang -> gagal dengan aman (bukan crash), semua sub-check
# ikut FAILED "dilewati" tanpa nyoba baca file yang emang udah nggak ada
# --------------------------------------------------------------------------


def test_36_missing_database_file_fails_safely(workdir):
    db_path = workdir / "tracker.db"
    app = make_app(db_path)
    with app.app_context():
        db.engine.dispose()
    os.remove(db_path)

    report = phc.Report(environment="test")
    result_path = phc.check_database_config_and_file(report, app)

    assert result_path is None
    by_name = {r.name: r for r in report.results}
    assert by_name["database_is_sqlite"].status == phc.STATUS_FAILED
    for name in (
        "database_file_exists",
        "database_readable",
        "database_select_1",
        "database_quick_check",
        "database_file_size",
    ):
        assert by_name[name].status == phc.STATUS_FAILED
    assert report.exit_code() == 1


# --------------------------------------------------------------------------
# 37: PRAGMA quick_check gagal -> dilaporkan sebagai FAILED
# --------------------------------------------------------------------------


def test_37_quick_check_failure_is_reported(workdir):
    db_path = workdir / "tracker.db"
    app = make_app(db_path)
    with app.app_context():
        db.engine.dispose()

    with open(db_path, "r+b") as f:
        f.seek(100)
        f.write(b"\xff" * 300)

    report = phc.Report(environment="test")
    phc.check_database_config_and_file(report, app)

    by_name = {r.name: r for r in report.results}
    assert by_name["database_quick_check"].status == phc.STATUS_FAILED
    assert report.exit_code() == 1


# --------------------------------------------------------------------------
# 38: belum ada backup sama sekali -> WARNING (bukan FAILED), exit code 0
# --------------------------------------------------------------------------


def test_38_missing_backup_produces_warning_not_failure(workdir, backup_dir, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKUP_DIR", str(backup_dir))
    db_path = workdir / "tracker.db"
    app = make_app(db_path)

    report = phc.Report(environment="test")
    phc.check_backups(report, app, db_path, stale_days=7)

    by_name = {r.name: r for r in report.results}
    assert by_name["backup_exists"].status == phc.STATUS_WARNING
    assert by_name["backup_exists"].required is False
    assert report.exit_code() == 0


# --------------------------------------------------------------------------
# 39: backup terbaru korup -> FAILED (WAJIB), exit code 1
# --------------------------------------------------------------------------


def test_39_corrupt_newest_backup_fails(workdir, backup_dir, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKUP_DIR", str(backup_dir))
    db_path = workdir / "tracker.db"
    app = make_app(db_path)

    result = dbc.create_backup(db_path, backup_dir, "test", timestamp="20260101-120000")
    with open(result.path, "r+b") as f:
        f.seek(100)
        f.write(b"\xff" * 300)

    report = phc.Report(environment="test")
    phc.check_backups(report, app, db_path, stale_days=7)

    by_name = {r.name: r for r in report.results}
    assert by_name["backup_integrity"].status == phc.STATUS_FAILED
    assert report.exit_code() == 1


# --------------------------------------------------------------------------
# 40: backup terbaru basi (lebih tua dari batas) -> WARNING, exit code 0
# --------------------------------------------------------------------------


def test_40_stale_backup_produces_warning(workdir, backup_dir, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKUP_DIR", str(backup_dir))
    db_path = workdir / "tracker.db"
    app = make_app(db_path)

    old_ts = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d-%H%M%S")
    dbc.create_backup(db_path, backup_dir, "test", timestamp=old_ts)

    report = phc.Report(environment="test")
    phc.check_backups(report, app, db_path, stale_days=7)

    by_name = {r.name: r for r in report.results}
    assert by_name["backup_integrity"].status == phc.STATUS_OK
    assert by_name["backup_age"].status == phc.STATUS_WARNING
    assert by_name["backup_age"].required is False
    assert report.exit_code() == 0


# --------------------------------------------------------------------------
# 41: checksum backup nggak cocok metadata -> FAILED, exit code 1
# --------------------------------------------------------------------------


def test_41_checksum_mismatch_fails(workdir, backup_dir, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKUP_DIR", str(backup_dir))
    db_path = workdir / "tracker.db"
    app = make_app(db_path)

    result = dbc.create_backup(db_path, backup_dir, "test", timestamp="20260101-120000")
    meta = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    meta["sha256"] = "0" * 64
    result.metadata_path.write_text(json.dumps(meta), encoding="utf-8")

    report = phc.Report(environment="test")
    phc.check_backups(report, app, db_path, stale_days=7)

    by_name = {r.name: r for r in report.results}
    assert by_name["backup_integrity"].status == phc.STATUS_OK
    assert by_name["backup_checksum"].status == phc.STATUS_FAILED
    assert report.exit_code() == 1


# --------------------------------------------------------------------------
# 42: config kritis hilang/nggak aman dilaporkan TANPA nampilin nilainya
# --------------------------------------------------------------------------


def test_42_missing_critical_config_is_reported_without_its_value(workdir):
    db_path = workdir / "tracker.db"
    app = make_app(db_path)
    app.config["SECRET_KEY"] = None

    report = phc.Report(environment="test")
    phc.check_critical_config(report, app)

    by_name = {r.name: r for r in report.results}
    assert by_name["critical_config"].status == phc.STATUS_FAILED
    assert "SECRET_KEY" in by_name["critical_config"].detail


def test_42b_insecure_default_secret_key_fails_without_leaking_it_twice(workdir):
    db_path = workdir / "tracker.db"
    app = make_app(db_path)
    app.config["SECRET_KEY"] = "dev-secret-key-ganti-di-production"

    report = phc.Report(environment="test")
    phc.check_critical_config(report, app)

    by_name = {r.name: r for r in report.results}
    assert by_name["critical_config"].status == phc.STATUS_FAILED


def test_42c_valid_critical_config_value_never_shown(workdir):
    db_path = workdir / "tracker.db"
    app = make_app(db_path)
    app.config["SECRET_KEY"] = "super-secret-pytest-value-xyz"

    report = phc.Report(environment="test")
    phc.check_critical_config(report, app)

    by_name = {r.name: r for r in report.results}
    assert by_name["critical_config"].status == phc.STATUS_OK
    assert "super-secret-pytest-value-xyz" not in by_name["critical_config"].detail


# --------------------------------------------------------------------------
# 43: disk space rendah terdeteksi (lewat mock shutil.disk_usage)
# --------------------------------------------------------------------------


def test_43_low_disk_space_detected_via_mock(workdir, monkeypatch):
    db_path = workdir / "tracker.db"
    app = make_app(db_path)

    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda path: _DiskUsage(total=10**10, used=10**10 - 100 * 1024 * 1024, free=100 * 1024 * 1024),
    )

    report = phc.Report(environment="test")
    phc.check_disk_space(report, app, min_free_mb=500)

    by_name = {r.name: r for r in report.results}
    assert by_name["disk_free_space"].status == phc.STATUS_WARNING
    assert by_name["disk_free_space"].required is False


def test_43b_sufficient_disk_space_is_ok_via_mock(workdir, monkeypatch):
    db_path = workdir / "tracker.db"
    app = make_app(db_path)

    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda path: _DiskUsage(total=10**10, used=1024, free=10**10 - 1024),
    )

    report = phc.Report(environment="test")
    phc.check_disk_space(report, app, min_free_mb=500)

    by_name = {r.name: r for r in report.results}
    assert by_name["disk_free_space"].status == phc.STATUS_OK


# --------------------------------------------------------------------------
# 44: output JSON penuh (report.to_dict()) nggak pernah ngandung secret
# --------------------------------------------------------------------------


def test_44_json_output_contains_no_secrets(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "totally-secret-pytest-value-abc123")

    # environment FLASK_ENV=testing (di-set global di conftest.py) bikin
    # create_app() bare di dalam phc.run() -> check_flask_app_creation()
    # pakai TestConfig (SQLite in-memory) — jadi TIDAK PERNAH nyentuh
    # instance/tracker.db asli walau dipanggil tanpa override eksplisit.
    report = phc.run("test-json-secrets", 7, 500)
    payload = json.dumps(report.to_dict())

    assert "totally-secret-pytest-value-abc123" not in payload
    assert "SECRET_KEY=" not in payload


# --------------------------------------------------------------------------
# 45: nggak ada satu pun test di file ini yang nyentuh instance/tracker.db
# asli — assertion eksplisit, sama polanya kayak test_backup_restore.py
# --------------------------------------------------------------------------


def test_45_never_touches_the_real_project_database(workdir):
    db_path = workdir / "isolated.db"
    app = make_app(db_path)
    resolved = dbc.resolve_active_sqlite_path(app)

    assert str(workdir.resolve()) in str(resolved)
    assert not str(resolved).startswith(str(Path(BACKEND_DIR).resolve() / "instance"))
    if REAL_INSTANCE_DB.exists():
        assert resolved != REAL_INSTANCE_DB.resolve()


def test_45b_running_the_full_report_leaves_the_real_database_file_untouched():
    if not REAL_INSTANCE_DB.exists():
        pytest.skip("instance/tracker.db belum ada di environment ini — nggak ada apa pun buat dibandingkan")

    before = REAL_INSTANCE_DB.stat().st_mtime_ns
    phc.run("test-real-db-untouched", 7, 500)
    after = REAL_INSTANCE_DB.stat().st_mtime_ns

    assert before == after


# --------------------------------------------------------------------------
# ekstra: required_packages check nggak pernah gagal di environment test
# sendiri (semua dependency wajib emang ke-install lewat requirements.txt)
# --------------------------------------------------------------------------


def test_required_packages_check_passes_in_this_environment():
    report = phc.Report(environment="test")
    phc.check_required_packages(report)

    by_name = {r.name: r for r in report.results}
    assert by_name["required_packages"].status == phc.STATUS_OK
