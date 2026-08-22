"""
Modul bersama buat scripts/backup_database.py dan scripts/restore_database.py
— logika path-resolution, validasi containment, integrity check, checksum,
dan atomic file replace SEHARUSNYA cuma ada di SATU tempat, biar kedua
script nggak punya 2 implementasi yang bisa diam-diam beda perilaku
(terutama buat hal sekritis validasi path backup/restore).

Modul ini SENGAJA nggak bergantung ke Flask app context di level fungsi
individual (kecuali resolve_active_sqlite_path yang emang butuh db.engine) —
biar gampang diuji terpisah dengan file SQLite biasa.

TIDAK PERNAH mencetak isi baris database, query SQL yang mengandung data
user, SECRET_KEY, token Telegram, atau dump environment variable.
"""

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

DEFAULT_BACKUP_DIR_ENV_VAR = "DATABASE_BACKUP_DIR"
DEFAULT_BACKUP_DIR = Path("~/database-backups")

# tracker-<environment>-<YYYYMMDD-HHMMSS>.db — sesuai contoh di spesifikasi
BACKUP_FILENAME_RE = re.compile(
    r"^tracker-(?P<environment>[a-z0-9][a-z0-9_-]{0,31})-(?P<timestamp>\d{8}-\d{6})\.db$"
)

# label environment: huruf kecil/angka/underscore/dash doang, mulai dari
# alnum, panjang 1-32 — SENGAJA nggak mengizinkan "/", "\", "..", spasi,
# ataupun karakter unicode aneh, biar nggak mungkin dipakai buat path
# traversal atau nyelundupin isi filename yang nggak diinginkan
ENVIRONMENT_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

_ENV_VAR_PLACEHOLDER_RE = re.compile(r"\$\{?\w+\}?|%\w+%")


class BackupError(Exception):
    """Kegagalan operasional yang harus dilaporkan dengan jelas ke operator (bukan bug internal)."""


@dataclass
class BackupResult:
    path: Path
    metadata_path: Optional[Path]
    filename: str
    environment: str
    timestamp: str
    size_bytes: int
    sha256: str
    integrity_ok: bool
    source_path: Path


@dataclass
class VerifyResult:
    path: Path
    integrity_ok: bool
    integrity_detail: str
    checksum_ok: Optional[bool]  # None kalau nggak ada metadata buat dibandingin
    metadata: Optional[dict] = field(default=None)


def log(message: str) -> None:
    """Satu baris log operasional ringkas, dengan timestamp — TIDAK PERNAH menerima isi data/secret sebagai argumen."""
    stamp = datetime.now().isoformat(timespec="seconds")
    print(f"[{stamp}] {message}")


def sanitize_environment_label(label: str) -> str:
    if not label or not isinstance(label, str):
        raise BackupError("Label environment kosong/tidak valid.")
    candidate = label.strip().lower()
    if not ENVIRONMENT_LABEL_RE.match(candidate):
        raise BackupError(
            f"Label environment {label!r} tidak valid — cuma boleh huruf kecil, angka, '-', '_', "
            "panjang 1-32 karakter, dan harus diawali huruf/angka (contoh: local, staging, production)."
        )
    return candidate


def resolve_environment_label(cli_value: Optional[str] = None) -> str:
    """
    Urutan prioritas: --environment eksplisit > env var BACKUP_ENVIRONMENT >
    FLASK_ENV (dipetakan) > fallback "local". Nggak pernah gagal total —
    kalau semuanya nggak jelas, jatuh ke "local" (paling aman, bukan
    "production"/"staging" yang salah tebak).
    """
    if cli_value:
        return sanitize_environment_label(cli_value)

    raw = os.environ.get("BACKUP_ENVIRONMENT") or os.environ.get("FLASK_ENV") or ""
    mapping = {
        "production": "production",
        "staging": "staging",
        "development": "local",
        "testing": "local",
    }
    guess = mapping.get(raw.strip().lower(), "local")
    return sanitize_environment_label(guess)


def parse_backup_filename(filename: str) -> Optional[dict]:
    m = BACKUP_FILENAME_RE.match(filename)
    if not m:
        return None
    return {"environment": m.group("environment"), "timestamp": m.group("timestamp")}


def timestamp_for_filename() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _assert_not_dangerous_target(resolved: Path, raw_original: str) -> None:
    """
    Jangan pernah biarkan path database aktif (buat backup ATAU restore)
    nunjuk ke lokasi berbahaya: root filesystem, home directory operator,
    root repo, atau path yang keliatannya masih ngandung placeholder env
    var yang belum ke-substitusi (mis. literal "$HOME" dari .env yang
    python-dotenv TIDAK melakukan shell expansion terhadapnya).
    """
    if _ENV_VAR_PLACEHOLDER_RE.search(raw_original):
        raise BackupError(
            f"DATABASE_URL sepertinya mengandung placeholder environment variable yang belum "
            f"ter-substitusi ({raw_original!r}) — perbaiki dulu konfigurasinya sebelum backup/restore."
        )

    dangerous = {Path.home().resolve(), Path(resolved.anchor or "/").resolve(), REPO_ROOT.resolve()}
    if resolved in dangerous:
        raise BackupError(f"Path database aktif menunjuk ke lokasi yang nggak aman buat dioperasikan: {resolved}")
    if resolved.is_dir():
        raise BackupError(f"Path database aktif ternyata sebuah folder, bukan file: {resolved}")


def resolve_sqlite_path_from_url(drivername: str, raw_database: Optional[str]) -> Path:
    """
    Bagian PURE (nggak butuh Flask app) dari resolve_active_sqlite_path di
    bawah — dipisah biar gampang diuji langsung dengan drivername/database
    string apa aja, TANPA perlu driver DB-API sungguhan ke-install (mis.
    psycopg2) cuma buat nguji cabang "tolak non-SQLite".
    """
    drivername = (drivername or "").lower()
    if not drivername.startswith("sqlite"):
        raise BackupError(
            f"Database yang dikonfigurasi bukan SQLite (drivername={drivername!r}) — "
            "script ini cuma aman dipakai buat database SQLite lokal."
        )

    if not raw_database or raw_database == ":memory:" or raw_database.startswith("file::memory:"):
        raise BackupError("Database yang dikonfigurasi adalah SQLite in-memory — nggak ada file buat di-backup/restore.")

    path = Path(raw_database)
    if not path.is_absolute():
        path = (BACKEND_DIR / path)
    resolved = path.resolve()

    _assert_not_dangerous_target(resolved, raw_database)

    if not resolved.is_file():
        raise BackupError(f"File database SQLite nggak ditemukan di path yang dikonfigurasi: {resolved}")

    return resolved


def resolve_active_sqlite_path(app) -> Path:
    """
    Ambil path file SQLite yang BENERAN dikonfigurasi Flask/SQLAlchemy app
    ini (bukan hardcode) — dan tolak kalau: bukan SQLite, in-memory, file
    filenya nggak ada, atau path-nya nggak aman buat dioperasikan.
    """
    from extensions import db

    with app.app_context():
        url = db.engine.url
        # kita cuma butuh baca config-nya, bukan nyimpen koneksi kebuka —
        # dispose() nutup semua koneksi yang lagi nganggur di connection
        # pool. Ini PENTING lebih dari sekadar higienis: di Windows, rename
        # atomic (os.replace) ke path yang MASIH punya handle file kebuka
        # bakal gagal ("Access is denied") — restore_database.py butuh
        # nge-replace file di path yang persis sama ini.
        db.engine.dispose()

    return resolve_sqlite_path_from_url(url.drivername, url.database)


def resolve_backup_dir(cli_value: Optional[str] = None, *, create: bool = False) -> Path:
    """
    Urutan prioritas: --backup-dir eksplisit > env var DATABASE_BACKUP_DIR >
    default ~/database-backups. Selalu dikembalikan sebagai absolute path
    yang udah di-resolve (symlink diikuti).
    """
    raw = cli_value or os.environ.get(DEFAULT_BACKUP_DIR_ENV_VAR) or str(DEFAULT_BACKUP_DIR)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path

    if create:
        path.mkdir(parents=True, exist_ok=True)

    return path.resolve()


def is_within_directory(path: Path, directory: Path) -> bool:
    """
    True kalau `path` (SUDAH di-resolve, symlink diikuti) beneran ada di
    dalam `directory` (SUDAH di-resolve juga). Symlink yang nunjuk keluar
    `directory` otomatis KEGAP di sini karena path.resolve() ngikutin
    symlink-nya ke lokasi ASLI sebelum dibandingin.
    """
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def check_integrity(sqlite_file: Path) -> tuple[bool, str]:
    """
    PRAGMA integrity_check terhadap 1 file SQLite, dibuka READ-ONLY (nggak
    mungkin ke-modifikasi apapun yang terjadi). Balikin (ok, detail) —
    `detail` cukup buat DIKEMBALIKAN ke caller (test, atau ditampilkan
    dalam bentuk RINGKASAN saja oleh CLI, bukan verbatim isi PRAGMA-nya
    yang berpotensi nyebut nama tabel/rowid).
    """
    uri = f"file:{sqlite_file.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as exc:
        return False, f"gagal membuka file: {exc.__class__.__name__}"

    try:
        try:
            rows = conn.execute("PRAGMA integrity_check;").fetchall()
        except sqlite3.DatabaseError:
            return False, "bukan file database SQLite yang valid"
    finally:
        conn.close()

    values = [r[0] for r in rows]
    ok = len(values) == 1 and str(values[0]).strip().lower() == "ok"
    detail = "ok" if ok else f"{len(values)} masalah ditemukan"
    return ok, detail


def sha256_of_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def count_tables(sqlite_file: Path) -> Optional[int]:
    """Jumlah tabel di file SQLite — proxy ringan buat "schema version" (struktural doang, bukan data)."""
    uri = f"file:{sqlite_file.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            (count,) = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table';").fetchone()
            return int(count)
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def write_json_atomic(path: Path, data: dict) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def sqlite_backup_copy(source_path: Path, dest_path: Path) -> None:
    """
    Salin database SQLite pakai Connection.backup() bawaan Python (yang
    ngebungkus SQLite Online Backup API asli) — konsisten walau ada
    koneksi lain yang lagi nulis ke source, TANPA mengunci/menghentikan
    aplikasi. Source dibuka READ-ONLY, jadi mustahil operasi ini nulis
    balik ke source.
    """
    src_uri = f"file:{source_path.as_posix()}?mode=ro"
    src_conn = sqlite3.connect(src_uri, uri=True)
    try:
        dst_conn = sqlite3.connect(str(dest_path))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def create_backup(
    source_path: Path,
    backup_dir: Path,
    environment: str,
    *,
    write_metadata: bool = True,
    timestamp: Optional[str] = None,
) -> BackupResult:
    """
    Inti mekanisme backup — dipakai LANGSUNG oleh backup_database.py (backup
    manual) DAN restore_database.py (safety-backup otomatis sebelum
    restore), biar dua-duanya punya jaminan keamanan yang SAMA PERSIS.

    Urutan: tulis ke file sementara DI DALAM backup_dir -> verifikasi
    integritas file sementara -> baru rename atomic ke nama final. Kalau
    ada langkah manapun gagal, cuma file sementara yang dihapus — source
    TIDAK PERNAH disentuh, dan file backup FINAL nggak pernah kebentuk
    dalam keadaan setengah jadi.
    """
    environment = sanitize_environment_label(environment)
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts = timestamp or timestamp_for_filename()
    filename = f"tracker-{environment}-{ts}.db"
    final_path = backup_dir / filename

    if final_path.exists():
        raise BackupError(
            f"File backup '{filename}' sudah ada di {backup_dir} — batal (kemungkinan dijalankan "
            "2x di detik yang sama). Coba lagi sesaat lagi."
        )

    tmp_path = backup_dir / f".{filename}.tmp-{os.getpid()}"
    if tmp_path.exists():
        tmp_path.unlink()

    try:
        sqlite_backup_copy(source_path, tmp_path)

        ok, detail = check_integrity(tmp_path)
        if not ok:
            raise BackupError(f"Verifikasi integritas backup GAGAL ({detail}) — backup dibatalkan, source tidak berubah.")

        size_bytes = tmp_path.stat().st_size
        checksum = sha256_of_file(tmp_path)

        os.replace(tmp_path, final_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

    metadata_path = None
    if write_metadata:
        metadata = {
            "backup_filename": filename,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "environment": environment,
            "source_table_count": count_tables(final_path),
            "file_size_bytes": size_bytes,
            "sha256": checksum,
            "integrity_check": "ok",
        }
        metadata_path = final_path.with_name(final_path.name + ".json")
        write_json_atomic(metadata_path, metadata)

    return BackupResult(
        path=final_path,
        metadata_path=metadata_path,
        filename=filename,
        environment=environment,
        timestamp=ts,
        size_bytes=size_bytes,
        sha256=checksum,
        integrity_ok=True,
        source_path=source_path,
    )


def load_metadata(backup_path: Path) -> Optional[dict]:
    meta_path = backup_path.with_name(backup_path.name + ".json")
    if not meta_path.is_file():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def resolve_and_validate_backup_path(raw_path: str, backup_dir: Path, *, allow_outside: bool = False) -> Path:
    """
    Validasi 1 path backup yang ditunjuk operator (--verify / --backup di
    restore): resolve absolute, WAJIB di dalam backup_dir (symlink yang
    nunjuk keluar otomatis kegap lewat resolve()) kecuali allow_outside
    eksplisit di-set, harus file biasa (bukan folder), harus berekstensi
    .db.
    """
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve()

    backup_dir_resolved = backup_dir.resolve()
    if not allow_outside and not is_within_directory(resolved, backup_dir_resolved):
        raise BackupError(
            f"File backup harus berada di dalam folder backup yang dikonfigurasi ({backup_dir_resolved}), "
            f"tapi dapat: {resolved}. Kalau ini beneran disengaja, pakai flag override eksplisit."
        )

    if not resolved.exists():
        raise BackupError(f"File backup nggak ditemukan: {resolved}")
    if not resolved.is_file():
        raise BackupError(f"Path backup bukan file biasa (mungkin folder): {resolved}")
    if resolved.suffix != ".db":
        raise BackupError(f"Path backup harus berekstensi .db: {resolved}")

    return resolved


def verify_backup(backup_path: Path, backup_dir: Path, *, allow_outside: bool = False) -> VerifyResult:
    resolved = resolve_and_validate_backup_path(str(backup_path), backup_dir, allow_outside=allow_outside)

    ok, detail = check_integrity(resolved)
    metadata = load_metadata(resolved)
    checksum_ok = None
    if metadata and metadata.get("sha256"):
        actual = sha256_of_file(resolved)
        checksum_ok = actual == metadata["sha256"]

    return VerifyResult(path=resolved, integrity_ok=ok, integrity_detail=detail, checksum_ok=checksum_ok, metadata=metadata)


def list_backups(backup_dir: Path) -> list[dict]:
    """
    Daftar backup yang valid di backup_dir — file lain (nggak cocok pola
    nama tracker-<env>-<timestamp>.db), folder, dan symlink yang nunjuk
    KELUAR backup_dir semuanya DIABAIKAN (bukan error), biar --list aman
    dipakai walau ada file lain nyasar di folder yang sama.
    """
    backup_dir_resolved = backup_dir.resolve()
    if not backup_dir_resolved.is_dir():
        return []

    entries = []
    for entry in sorted(backup_dir_resolved.iterdir()):
        if entry.name.endswith(".json"):
            continue
        if entry.is_dir():
            continue
        parsed = parse_backup_filename(entry.name)
        if not parsed:
            continue
        resolved = entry.resolve()
        if not is_within_directory(resolved, backup_dir_resolved):
            continue  # symlink escaping backup_dir -> diabaikan
        if not resolved.is_file():
            continue
        stat = resolved.stat()
        meta_path = resolved.with_name(resolved.name + ".json")
        entries.append(
            {
                "filename": entry.name,
                "path": resolved,
                "environment": parsed["environment"],
                "timestamp": parsed["timestamp"],
                "size_bytes": stat.st_size,
                "has_metadata": meta_path.is_file(),
            }
        )
    return entries


def prune_backups(backup_dir: Path, keep: int, *, apply: bool = False, protect: Optional[set] = None) -> dict:
    """
    Dry-run secara DEFAULT (apply=False) — cuma nentuin & ngelaporin apa
    yang AKAN dihapus. Backup TERBARU (berdasarkan timestamp di nama file)
    nggak pernah masuk daftar hapus, apapun nilai `keep`-nya. `protect`
    (opsional) buat nge-exclude path tertentu tambahan (mis. safety backup
    yang baru aja dibikin di operasi yang sama).
    """
    protect = protect or set()
    backup_dir_resolved = backup_dir.resolve()
    entries = list_backups(backup_dir_resolved)
    entries.sort(key=lambda e: e["timestamp"], reverse=True)

    newest_path = entries[0]["path"] if entries else None
    to_delete_candidates = entries[keep:] if keep >= 0 else entries

    final_delete = []
    for e in to_delete_candidates:
        if newest_path is not None and e["path"] == newest_path:
            continue
        if e["path"] in protect:
            continue
        if not is_within_directory(e["path"], backup_dir_resolved):
            continue
        final_delete.append(e)

    if apply:
        for e in final_delete:
            e["path"].unlink(missing_ok=True)
            meta_path = e["path"].with_name(e["path"].name + ".json")
            if meta_path.is_file() and is_within_directory(meta_path.resolve(), backup_dir_resolved):
                meta_path.unlink(missing_ok=True)

    kept = [e for e in entries if e not in final_delete]
    return {"kept": kept, "to_delete": final_delete, "applied": apply}
