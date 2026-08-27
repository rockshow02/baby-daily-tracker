"""
Diagnostik manual database + deployment — buat dijalankan operator dari
Bash console PythonAnywhere (nggak ada scheduled task di free tier, jadi
ini SENGAJA manual, bukan otomatis).

READ-ONLY terhadap database (nggak pernah nulis/ubah/hapus apa pun di
sana) dan nggak pernah bikin backup baru sendiri — cuma MEMERIKSA backup
yang udah ada (lihat scripts/backup_database.py buat bikin backup).
Satu-satunya tulis-ke-disk yang mungkin terjadi: 1 file probe kecil yang
dibikin DAN dihapus lagi di folder upload (buat ngecek writable), kalau
folder upload itu emang dipakai.

TIDAK PERNAH mencetak: isi baris database, nilai SECRET_KEY/config lain,
DATABASE_URL lengkap, atau apa pun yang bisa bocorin path/kredensial.

CARA PAKAI (Bash console PythonAnywhere):
  cd ~/baby-daily-tracker/backend
  source ~/.virtualenvs/babytracker-venv/bin/activate
  python scripts/production_health_check.py --environment staging

  # opsional:
  python scripts/production_health_check.py --environment production \
      --backup-stale-days 7 --min-disk-free-mb 500 --json

Kode keluar:
  0 = semua pengecekan WAJIB lolos (WARNING boleh ada)
  1 = minimal 1 pengecekan WAJIB gagal
  2 = penggunaan command / konfigurasi salah
"""

import argparse
import importlib
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_backup_common import (  # noqa: E402
    BackupError,
    list_backups,
    resolve_active_sqlite_path,
    resolve_backup_dir,
    sanitize_environment_label,
    verify_backup,
)

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_FAILED = "FAILED"

REQUIRED_PACKAGES = ("flask", "flask_sqlalchemy", "flask_cors", "dotenv", "requests", "reportlab", "feedparser", "qrcode")
CRITICAL_CONFIG_KEYS = ("SECRET_KEY", "SQLALCHEMY_DATABASE_URI")
_INSECURE_DEFAULT_SECRET_KEY = "dev-secret-key-ganti-di-production"

DEFAULT_BACKUP_STALE_DAYS = 7
DEFAULT_MIN_DISK_FREE_MB = 500
DEFAULT_DB_TIMEOUT_SECONDS = 2.0

# Tabel yang wajib tersedia sesudah migrasi V3. Nama saja, tidak pernah
# membaca isi/row count sehingga pemeriksaan tetap privacy-safe dan read-only.
V3_REQUIRED_TABLES = (
    "memory_journal_entries", "memory_journal_metadata", "memory_journal_tags",
    "development_goals", "family_development_check_ins", "appointment_preparations",
)


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    required: bool = True


@dataclass
class Report:
    environment: str
    results: list = field(default_factory=list)

    def add(self, name, status, detail="", required=True):
        self.results.append(CheckResult(name=name, status=status, detail=detail, required=required))

    def exit_code(self):
        if any(r.status == STATUS_FAILED and r.required for r in self.results):
            return 1
        return 0

    def to_dict(self):
        return {
            "environment": self.environment,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "checks": [
                {"name": r.name, "status": r.status, "detail": r.detail, "required": r.required}
                for r in self.results
            ],
            "exit_code": self.exit_code(),
        }


def _print_human(report: Report):
    print(f"Production health check — environment: {report.environment}")
    print("-" * 60)
    width = max((len(r.name) for r in report.results), default=10)
    for r in report.results:
        marker = "*" if not r.required else " "
        line = f"[{r.status:<7}]{marker} {r.name:<{width}}"
        if r.detail:
            line += f" — {r.detail}"
        print(line)
    print("-" * 60)
    counts = {STATUS_OK: 0, STATUS_WARNING: 0, STATUS_FAILED: 0}
    for r in report.results:
        counts[r.status] = counts.get(r.status, 0) + 1
    print(f"OK={counts.get(STATUS_OK, 0)} WARNING={counts.get(STATUS_WARNING, 0)} FAILED={counts.get(STATUS_FAILED, 0)}")
    print("(* = pengecekan opsional, kegagalannya nggak mempengaruhi exit code)")


# --------------------------------------------------------------------------
# Masing-masing pengecekan — SEMUA dibungkus try/except di pemanggilnya
# (main()), biar 1 pengecekan gagal nggak bikin sisanya nggak sempat jalan.
# --------------------------------------------------------------------------


def check_flask_app_creation(report: Report):
    try:
        from app import create_app

        app = create_app()
        report.add("flask_app_creation", STATUS_OK, "Flask app berhasil dibikin")
        return app
    except Exception as exc:
        report.add("flask_app_creation", STATUS_FAILED, f"Gagal bikin Flask app ({exc.__class__.__name__})")
        return None


def check_database_config_and_file(report: Report, app):
    """Checks 2-7: config SQLite, file ada, bisa dibaca, SELECT 1, quick_check, ukuran file."""
    if app is None:
        for name in ("database_is_sqlite", "database_file_exists", "database_readable", "database_select_1", "database_quick_check", "database_file_size"):
            report.add(name, STATUS_FAILED, "dilewati — Flask app nggak berhasil dibikin")
        return None

    try:
        db_path = resolve_active_sqlite_path(app)
        report.add("database_is_sqlite", STATUS_OK, "Konfigurasi database SQLite lokal, path valid")
    except BackupError as exc:
        report.add("database_is_sqlite", STATUS_FAILED, str(exc))
        for name in ("database_file_exists", "database_readable", "database_select_1", "database_quick_check", "database_file_size"):
            report.add(name, STATUS_FAILED, "dilewati — path database nggak valid")
        return None

    if not db_path.is_file():
        report.add("database_file_exists", STATUS_FAILED, "File database nggak ditemukan")
        for name in ("database_readable", "database_select_1", "database_quick_check", "database_file_size"):
            report.add(name, STATUS_FAILED, "dilewati — file database nggak ada")
        return db_path
    report.add("database_file_exists", STATUS_OK, "File database ada")

    if not os.access(db_path, os.R_OK):
        report.add("database_readable", STATUS_FAILED, "File database nggak bisa dibaca (permission)")
    else:
        report.add("database_readable", STATUS_OK, "File database bisa dibaca")

    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=DEFAULT_DB_TIMEOUT_SECONDS)
        try:
            conn.execute("SELECT 1;").fetchone()
            report.add("database_select_1", STATUS_OK, "SELECT 1 berhasil")
        finally:
            conn.close()
    except Exception as exc:
        report.add("database_select_1", STATUS_FAILED, f"SELECT 1 gagal ({exc.__class__.__name__})")

    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=DEFAULT_DB_TIMEOUT_SECONDS)
        try:
            rows = conn.execute("PRAGMA quick_check;").fetchall()
            ok = len(rows) == 1 and str(rows[0][0]).strip().lower() == "ok"
            if ok:
                report.add("database_quick_check", STATUS_OK, "PRAGMA quick_check: ok")
            else:
                report.add("database_quick_check", STATUS_FAILED, f"PRAGMA quick_check menemukan {len(rows)} masalah")
        finally:
            conn.close()
    except Exception as exc:
        report.add("database_quick_check", STATUS_FAILED, f"quick_check gagal dijalankan ({exc.__class__.__name__})")

    try:
        size_bytes = db_path.stat().st_size
        report.add("database_file_size", STATUS_OK, f"{size_bytes} bytes")
    except OSError as exc:
        report.add("database_file_size", STATUS_FAILED, f"Gagal baca ukuran file ({exc.__class__.__name__})")

    return db_path


def check_v3_schema(report: Report, db_path):
    """Pastikan migrasi tabel V3 sudah dijalankan tanpa membaca data user."""
    if db_path is None or not db_path.is_file():
        report.add("v3_schema", STATUS_FAILED, "dilewati — file database nggak tersedia")
        return
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=DEFAULT_DB_TIMEOUT_SECONDS)
        try:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        finally:
            conn.close()
        existing = {str(row[0]) for row in rows}
        missing = sorted(set(V3_REQUIRED_TABLES) - existing)
        if missing:
            report.add("v3_schema", STATUS_FAILED,
                       f"{len(missing)} tabel V3 belum ada — jalankan scripts/migrate_production.py")
        else:
            report.add("v3_schema", STATUS_OK, f"Semua {len(V3_REQUIRED_TABLES)} tabel V3 tersedia")
    except Exception as exc:
        report.add("v3_schema", STATUS_FAILED, f"Schema V3 nggak bisa diperiksa ({exc.__class__.__name__})")


def check_backups(report: Report, app, db_path, stale_days: int):
    """Checks 8-13: folder backup, minimal 1 backup, integrity+checksum backup terbaru, umur backup."""
    try:
        backup_dir = resolve_backup_dir(None, create=False, active_db_path=db_path)
        report.add("backup_directory", STATUS_OK, "Folder backup ter-resolve dengan aman", required=True)
    except BackupError as exc:
        report.add("backup_directory", STATUS_FAILED, str(exc), required=True)
        for name in ("backup_exists", "backup_integrity", "backup_checksum", "backup_age"):
            report.add(name, STATUS_WARNING, "dilewati — folder backup nggak ter-resolve", required=False)
        return

    try:
        entries = list_backups(backup_dir, active_db_path=db_path)
    except BackupError as exc:
        report.add("backup_exists", STATUS_WARNING, f"Gagal membaca folder backup ({exc.__class__.__name__})", required=False)
        return

    if not entries:
        report.add("backup_exists", STATUS_WARNING, "Belum ada backup sama sekali — jalankan scripts/backup_database.py", required=False)
        return

    newest = max(entries, key=lambda e: e["timestamp"])
    report.add("backup_exists", STATUS_OK, f"{len(entries)} backup ditemukan", required=False)

    try:
        verify_result = verify_backup(newest["path"], backup_dir, active_db_path=db_path)
    except BackupError as exc:
        report.add("backup_integrity", STATUS_FAILED, f"Backup terbaru nggak bisa diverifikasi ({exc.__class__.__name__})")
        return

    if verify_result.integrity_ok:
        report.add("backup_integrity", STATUS_OK, "Backup terbaru lolos integrity check")
    else:
        report.add("backup_integrity", STATUS_FAILED, f"Backup terbaru GAGAL integrity check ({verify_result.integrity_detail})")

    if verify_result.checksum_ok is None:
        report.add("backup_checksum", STATUS_OK, "Nggak ada metadata checksum buat dibandingkan", required=False)
    elif verify_result.checksum_ok:
        report.add("backup_checksum", STATUS_OK, "Checksum backup terbaru cocok metadata")
    else:
        report.add("backup_checksum", STATUS_FAILED, "Checksum backup terbaru TIDAK COCOK metadata — file mungkin rusak/berubah")

    try:
        backup_dt = datetime.strptime(newest["timestamp"], "%Y%m%d-%H%M%S")
        age_days = (datetime.now() - backup_dt).total_seconds() / 86400
        age_detail = f"backup terbaru berumur {age_days:.1f} hari ({newest['timestamp']})"
        if age_days > stale_days:
            report.add("backup_age", STATUS_WARNING, f"{age_detail} — lebih tua dari batas {stale_days} hari", required=False)
        else:
            report.add("backup_age", STATUS_OK, age_detail, required=False)
    except ValueError:
        report.add("backup_age", STATUS_WARNING, "Nggak bisa memparse timestamp backup terbaru", required=False)


def check_required_packages(report: Report):
    missing = []
    for package in REQUIRED_PACKAGES:
        try:
            importlib.import_module(package)
        except Exception:
            missing.append(package)
    if missing:
        report.add("required_packages", STATUS_FAILED, f"{len(missing)} package gagal di-import: {', '.join(missing)}")
    else:
        report.add("required_packages", STATUS_OK, f"Semua {len(REQUIRED_PACKAGES)} package inti berhasil di-import")


_REQUESTS_WARNING_PROBE = (
    "import warnings\n"
    "import requests.exceptions\n"
    "with warnings.catch_warnings():\n"
    "    warnings.simplefilter('error', category=requests.exceptions.RequestsDependencyWarning)\n"
    "    import importlib\n"
    "    importlib.reload(requests)\n"
)


def check_requests_dependency_warning(report: Report):
    """
    Dijalankan di SUBPROCESS terpisah (interpreter Python yang sama),
    BUKAN reload() modul di proses yang lagi jalan ini — biar nggak ada
    efek samping ke sisa eksekusi script diagnostik ini sendiri.
    `requests` sendiri kemungkinan udah ke-import transitif lewat
    check_flask_app_creation() di atas (lewat utils/telegram.py), jadi
    import biasa aja nggak cukup buat memicu ulang pengecekan
    kompatibilitasnya — makanya perlu reload() di proses terpisah itu.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-c", _REQUESTS_WARNING_PROBE],
            capture_output=True,
            timeout=15,
        )
        if result.returncode == 0:
            report.add("requests_dependency_warning", STATUS_OK, "requests import tanpa RequestsDependencyWarning")
        else:
            report.add(
                "requests_dependency_warning",
                STATUS_FAILED,
                "RequestsDependencyWarning terdeteksi — lihat backend/docs/DEPENDENCIES.md",
            )
    except Exception as exc:
        report.add("requests_dependency_warning", STATUS_WARNING, f"Nggak bisa dicek ({exc.__class__.__name__})", required=False)


def check_critical_config(report: Report, app):
    if app is None:
        report.add("critical_config", STATUS_FAILED, "dilewati — Flask app nggak berhasil dibikin")
        return

    missing = [key for key in CRITICAL_CONFIG_KEYS if not app.config.get(key)]
    if missing:
        report.add("critical_config", STATUS_FAILED, f"{len(missing)} config kritis kosong: {', '.join(missing)}")
        return

    if app.config.get("SECRET_KEY") == _INSECURE_DEFAULT_SECRET_KEY:
        report.add("critical_config", STATUS_FAILED, "SECRET_KEY masih nilai default dev — WAJIB diganti di production")
        return

    report.add("critical_config", STATUS_OK, f"Semua {len(CRITICAL_CONFIG_KEYS)} config kritis ada (nilai tidak ditampilkan)")


def check_upload_directory(report: Report, app):
    if app is None:
        report.add("upload_directory", STATUS_WARNING, "dilewati — Flask app nggak berhasil dibikin", required=False)
        return

    uploads_dir = Path(app.root_path) / "uploads"
    if not uploads_dir.is_dir():
        report.add("upload_directory", STATUS_WARNING, "Folder uploads/ nggak ditemukan", required=False)
        return

    probe_path = uploads_dir / f".health-check-probe-{os.getpid()}.tmp"
    try:
        probe_path.write_bytes(b"probe")
        probe_path.unlink()
        report.add("upload_directory", STATUS_OK, "Folder uploads/ ada dan bisa ditulis", required=False)
    except OSError as exc:
        report.add("upload_directory", STATUS_WARNING, f"Folder uploads/ ada tapi nggak bisa ditulis ({exc.__class__.__name__})", required=False)
    finally:
        if probe_path.exists():
            try:
                probe_path.unlink()
            except OSError:
                pass


def check_disk_space(report: Report, app, min_free_mb: int):
    import shutil

    target_dir = Path(app.root_path) if app is not None else Path(__file__).resolve().parent.parent
    try:
        usage = shutil.disk_usage(target_dir)
        free_mb = usage.free / (1024 * 1024)
        if free_mb < min_free_mb:
            report.add("disk_free_space", STATUS_WARNING, f"{free_mb:.0f} MB tersisa (batas {min_free_mb} MB)", required=False)
        else:
            report.add("disk_free_space", STATUS_OK, f"{free_mb:.0f} MB tersisa", required=False)
    except OSError as exc:
        report.add("disk_free_space", STATUS_WARNING, f"Gagal cek disk space ({exc.__class__.__name__})", required=False)


def run(environment: str, stale_days: int, min_disk_free_mb: int) -> Report:
    report = Report(environment=environment)

    app = check_flask_app_creation(report)
    db_path = check_database_config_and_file(report, app)
    check_v3_schema(report, db_path)
    check_backups(report, app, db_path, stale_days)
    check_required_packages(report)
    check_requests_dependency_warning(report)
    check_critical_config(report, app)
    check_upload_directory(report, app)
    check_disk_space(report, app, min_disk_free_mb)

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--environment", default="local", help="Label environment (local/staging/production, dst) — cuma buat ditampilkan di laporan.")
    parser.add_argument("--backup-stale-days", type=int, default=DEFAULT_BACKUP_STALE_DAYS, help=f"Umur maksimal backup terbaru sebelum di-WARNING (default: {DEFAULT_BACKUP_STALE_DAYS} hari).")
    parser.add_argument("--min-disk-free-mb", type=int, default=DEFAULT_MIN_DISK_FREE_MB, help=f"Batas minimal disk free sebelum di-WARNING (default: {DEFAULT_MIN_DISK_FREE_MB} MB).")
    parser.add_argument("--json", action="store_true", help="Output JSON (tetap privacy-safe — cuma status/detail per pengecekan).")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        environment = sanitize_environment_label(args.environment)
    except BackupError as exc:
        print(f"GAGAL: {exc}", file=sys.stderr)
        return 2

    if args.backup_stale_days <= 0 or args.min_disk_free_mb < 0:
        print("GAGAL: --backup-stale-days harus > 0 dan --min-disk-free-mb harus >= 0", file=sys.stderr)
        return 2

    report = run(environment, args.backup_stale_days, args.min_disk_free_mb)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        _print_human(report)

    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main())
