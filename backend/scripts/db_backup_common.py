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

# --keep minimal — setidaknya 1 backup WAJIB dipertahankan eksplisit, nggak
# boleh 0 (apalagi negatif), biar --prune nggak pernah bisa ngosongin folder
# backup sama sekali dalam 1 kali jalan.
MIN_KEEP = 1

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


def validate_backup_directory(raw_value: Optional[str], *, active_db_path: Optional[Path] = None) -> Path:
    """
    Validasi 1 folder backup CALON (belum tentu ada di disk) — dipanggil di
    SETIAP operasi yang menyentuh backup_dir (create/list/verify/restore/
    prune), BUKAN cuma di titik masuk CLI, biar fungsi inti (create_backup,
    list_backups, verify_backup, prune_backups) tetep melindungi diri
    sendiri walau dipanggil langsung dari test/script lain, bukan cuma
    lewat argparse.

    Menolak:
    - nilai kosong/ambigu
    - placeholder environment variable yang belum ter-substitusi
      ($HOME, ${HOME}, %USERPROFILE%, dst)
    - root filesystem (POSIX "/" ATAU drive root Windows kayak "C:\\")
    - home directory operator
    - root repository
    - root folder backend
    - folder backend/instance
    - folder induk database aktif (kalau active_db_path dikasih)
    - path database aktif itu sendiri (kalau active_db_path dikasih)
    - symlink yang RESOLVE ke salah satu lokasi di atas (path.resolve()
      ngikutin symlink ke lokasi ASLI-nya sebelum semua pengecekan di atas
      dijalankan)
    - path yang udah ada sebagai FILE biasa (bukan folder)
    - path yang nggak bisa di-resolve dengan aman (mis. symlink loop)

    SENGAJA cuma nolak lokasi-lokasi itu PERSIS (exact match), BUKAN semua
    yang ada DI BAWAHNYA — folder khusus kayak ~/database-backups atau
    ~/database-backups/staging harus TETAP valid walau ada di bawah home
    directory.
    """
    if raw_value is None or not str(raw_value).strip():
        raise BackupError("Folder backup kosong/tidak valid — nggak bisa dipakai.")

    raw_str = str(raw_value)
    if _ENV_VAR_PLACEHOLDER_RE.search(raw_str):
        raise BackupError(
            f"Folder backup sepertinya mengandung placeholder environment variable yang belum "
            f"ter-substitusi ({raw_str!r}) — perbaiki dulu nilainya (--backup-dir atau env var "
            f"{DEFAULT_BACKUP_DIR_ENV_VAR})."
        )

    path = Path(raw_str).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path

    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        raise BackupError(f"Folder backup {raw_str!r} nggak bisa di-resolve dengan aman: {exc}")

    if resolved.parent == resolved:
        raise BackupError(f"Folder backup nggak boleh berupa root filesystem: {resolved}")

    forbidden = {
        Path.home().resolve(): "home directory operator",
        REPO_ROOT.resolve(): "root repository",
        BACKEND_DIR.resolve(): "root folder backend",
        (BACKEND_DIR / "instance").resolve(): "folder instance/ backend",
    }
    if active_db_path is not None:
        try:
            active_resolved = Path(active_db_path).resolve()
            forbidden[active_resolved] = "path database aktif itu sendiri"
            forbidden[active_resolved.parent] = "folder induk database aktif"
        except (OSError, RuntimeError):
            pass  # kalau active_db_path-nya sendiri nggak valid, itu urusan pemanggilnya — jangan gagalin validasi folder backup di sini

    if resolved in forbidden:
        raise BackupError(
            f"Folder backup nggak boleh menunjuk ke {forbidden[resolved]} ({resolved}) — "
            "pakai folder khusus buat backup, misalnya ~/database-backups."
        )

    if resolved.is_file():
        raise BackupError(f"Folder backup ternyata sebuah file biasa, bukan folder: {resolved}")

    return resolved


def resolve_backup_dir(
    cli_value: Optional[str] = None,
    *,
    create: bool = False,
    active_db_path: Optional[Path] = None,
) -> Path:
    """
    Urutan prioritas: --backup-dir eksplisit > env var DATABASE_BACKUP_DIR >
    default ~/database-backups. Selalu dikembalikan sebagai absolute path
    yang udah di-resolve DAN tervalidasi (lihat validate_backup_directory).
    """
    raw = cli_value or os.environ.get(DEFAULT_BACKUP_DIR_ENV_VAR) or str(DEFAULT_BACKUP_DIR)
    resolved = validate_backup_directory(raw, active_db_path=active_db_path)

    if create:
        resolved.mkdir(parents=True, exist_ok=True)

    return resolved


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
    # revalidasi backup_dir DI SINI JUGA (bukan cuma percaya pemanggilnya
    # udah bener) — create_backup() dipanggil LANGSUNG oleh restore_database.py
    # (safety backup) dan bisa dipanggil langsung oleh script/test lain,
    # jadi fungsi inti ini juga wajib melindungi diri sendiri, bukan cuma
    # CLI-nya doang. `source_path` (database yang lagi di-backup) dikasih
    # sebagai konteks active_db_path — dua-duanya (backup manual & safety
    # backup restore) SELALU nge-backup database yang lagi aktif.
    backup_dir = validate_backup_directory(str(backup_dir), active_db_path=source_path)
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


def verify_backup(
    backup_path: Path,
    backup_dir: Path,
    *,
    allow_outside: bool = False,
    active_db_path: Optional[Path] = None,
) -> VerifyResult:
    backup_dir = validate_backup_directory(str(backup_dir), active_db_path=active_db_path)
    resolved = resolve_and_validate_backup_path(str(backup_path), backup_dir, allow_outside=allow_outside)

    ok, detail = check_integrity(resolved)
    metadata = load_metadata(resolved)
    checksum_ok = None
    if metadata and metadata.get("sha256"):
        actual = sha256_of_file(resolved)
        checksum_ok = actual == metadata["sha256"]

    return VerifyResult(path=resolved, integrity_ok=ok, integrity_detail=detail, checksum_ok=checksum_ok, metadata=metadata)


def list_backups(backup_dir: Path, *, active_db_path: Optional[Path] = None) -> list[dict]:
    """
    Daftar backup yang valid di backup_dir — file lain (nggak cocok pola
    nama tracker-<env>-<timestamp>.db), folder, dan symlink yang nunjuk
    KELUAR backup_dir semuanya DIABAIKAN (bukan error), biar --list aman
    dipakai walau ada file lain nyasar di folder yang sama.
    """
    backup_dir_resolved = validate_backup_directory(str(backup_dir), active_db_path=active_db_path)
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


def _revalidate_deletion_candidate(
    path: Path,
    backup_dir_resolved: Path,
    *,
    newest_path: Optional[Path],
    protect: set,
) -> Path:
    """
    Validasi ULANG 1 kandidat file TEPAT SEBELUM beneran di-unlink() —
    dipanggil lagi di sini, BUKAN cuma percaya hasil listing di awal, buat
    ngurangin risiko time-of-check/time-of-use (mis. file itu diganti jadi
    symlink, atau dipindah keluar folder, ANTARA saat listing awal dan saat
    penghapusan beneran dieksekusi).
    """
    if path.is_symlink():
        raise BackupError(f"Batal hapus — target ternyata symlink (nggak diizinkan): {path}")

    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise BackupError(f"Batal hapus — target nggak bisa di-resolve ulang dengan aman ({exc}): {path}")

    if resolved != path:
        raise BackupError(f"Batal hapus — target berubah antara listing dan penghapusan: {path} -> {resolved}")

    if not is_within_directory(resolved, backup_dir_resolved):
        raise BackupError(f"Batal hapus — target ternyata di LUAR folder backup yang tervalidasi: {resolved}")

    if newest_path is not None and resolved == newest_path:
        raise BackupError(f"Batal hapus — target ternyata backup TERBARU (selalu dilindungi): {resolved}")

    if resolved in protect:
        raise BackupError(f"Batal hapus — target dilindungi eksplisit (mis. safety backup operasi ini): {resolved}")

    if not parse_backup_filename(resolved.name):
        raise BackupError(f"Batal hapus — nama file nggak cocok pola backup yang dibuat script ini: {resolved.name}")

    if not resolved.is_file():
        raise BackupError(f"Batal hapus — target bukan file biasa: {resolved}")

    return resolved


def _revalidate_metadata_deletion_candidate(backup_resolved: Path, backup_dir_resolved: Path) -> Optional[Path]:
    """
    Sama kayak _revalidate_deletion_candidate, tapi buat file metadata .json
    yang PERSIS bersebelahan sama 1 backup yang barusan divalidasi ulang.
    Cuma nama PERSIS "<nama-backup>.json" yang dipertimbangkan — nggak ada
    file .json lain yang boleh ikut tersentuh oleh operasi ini.
    """
    meta_path = backup_resolved.with_name(backup_resolved.name + ".json")
    if not meta_path.exists() and not meta_path.is_symlink():
        return None  # nggak ada metadata — nggak masalah, memang opsional

    if meta_path.is_symlink():
        raise BackupError(f"Batal hapus metadata — target ternyata symlink (nggak diizinkan): {meta_path}")

    try:
        resolved_meta = meta_path.resolve(strict=True)
    except OSError as exc:
        raise BackupError(f"Batal hapus metadata — nggak bisa di-resolve ulang dengan aman ({exc}): {meta_path}")

    if resolved_meta != meta_path:
        raise BackupError(f"Batal hapus metadata — target berubah antara listing dan penghapusan: {meta_path} -> {resolved_meta}")

    if not is_within_directory(resolved_meta, backup_dir_resolved):
        raise BackupError(f"Batal hapus metadata — ternyata di LUAR folder backup yang tervalidasi: {resolved_meta}")

    if resolved_meta.name != backup_resolved.name + ".json":
        raise BackupError(f"Batal hapus metadata — nama nggak cocok PERSIS dengan backup-nya: {resolved_meta}")

    if not resolved_meta.is_file():
        raise BackupError(f"Batal hapus metadata — bukan file biasa: {resolved_meta}")

    return resolved_meta


def prune_backups(
    backup_dir: Path,
    keep: int,
    *,
    apply: bool = False,
    protect: Optional[set] = None,
    active_db_path: Optional[Path] = None,
) -> dict:
    """
    Dry-run secara DEFAULT (apply=False) — cuma nentuin & ngelaporin apa
    yang AKAN dihapus, TIDAK PERNAH beneran menghapus apa pun. Backup
    TERBARU (berdasarkan timestamp di nama file) nggak pernah masuk daftar
    hapus, apapun nilai `keep`-nya. `protect` (opsional) buat nge-exclude
    path tertentu tambahan (mis. safety backup yang baru aja dibikin di
    operasi yang sama).

    `keep` WAJIB >= MIN_KEEP — ini dicek di sini (fungsi inti), bukan cuma
    di level CLI, biar pemanggil langsung (test/script lain) juga kena.

    Skema hasil (SELALU dikembalikan, baik dry-run maupun apply):
    - existing             : semua backup valid yang ADA SEKARANG (sebelum operasi apa pun)
    - to_delete             : kandidat yang AKAN (dry-run) atau DICOBA (apply) dihapus
    - deleted               : yang BENERAN berhasil dihapus — kosong kalau dry-run,
                              subset dari to_delete kalau apply (bisa < to_delete kalau abort di tengah)
    - remaining_after_apply : proyeksi (dry-run) ATAU sisa AKTUAL (apply) setelah operasi
    - applied               : True kalau apply BENERAN dijalankan (bukan cuma diminta)
    - aborted               : True kalau apply dihentikan di tengah jalan karena revalidasi gagal
    - abort_reason          : pesan penjelasan kalau aborted True, None kalau nggak

    Kalau apply dihentikan di tengah, backup yang UDAH kehapus TETAP kehapus
    (nggak bisa "dibatalkan mundur") — deleted mencerminkan itu secara jujur,
    dan aborted+abort_reason menjelaskan kenapa sisanya nggak ikut dihapus.
    """
    if keep < MIN_KEEP:
        raise BackupError(f"--keep harus >= {MIN_KEEP} (minimal 1 backup wajib dipertahankan eksplisit), dapat: {keep}")

    protect = protect or set()
    backup_dir_resolved = validate_backup_directory(str(backup_dir), active_db_path=active_db_path)
    existing = list_backups(backup_dir_resolved, active_db_path=active_db_path)
    existing_sorted = sorted(existing, key=lambda e: e["timestamp"], reverse=True)

    newest_path = existing_sorted[0]["path"] if existing_sorted else None
    to_delete_candidates = existing_sorted[keep:]

    final_delete = []
    for e in to_delete_candidates:
        if newest_path is not None and e["path"] == newest_path:
            continue
        if e["path"] in protect:
            continue
        if not is_within_directory(e["path"], backup_dir_resolved):
            continue
        final_delete.append(e)

    to_delete_paths = {e["path"] for e in final_delete}
    remaining_projected = [e for e in existing_sorted if e["path"] not in to_delete_paths]

    result = {
        "existing": existing_sorted,
        "to_delete": final_delete,
        "deleted": [],
        "remaining_after_apply": remaining_projected,
        "applied": False,
        "aborted": False,
        "abort_reason": None,
    }

    if not apply:
        return result

    # revalidasi folder backup-nya sendiri lagi TEPAT SEBELUM mulai
    # menghapus apa pun — jaga-jaga kalau backup_dir sempat "berubah"
    # (mis. ditimpa symlink) antara resolusi awal dan mulai eksekusi
    revalidated_dir = validate_backup_directory(str(backup_dir_resolved), active_db_path=active_db_path)
    if revalidated_dir != backup_dir_resolved:
        raise BackupError(
            f"Folder backup berubah antara validasi awal dan mulai penghapusan "
            f"({backup_dir_resolved} -> {revalidated_dir}) — dibatalkan demi keamanan, tidak ada yang dihapus."
        )

    deleted = []
    for e in final_delete:
        # revalidasi DAN eksekusi unlink()-nya sendiri SAMA-SAMA di dalam
        # try/except yang sama — kegagalan beneran pas unlink() (disk
        # error, permission, file kekunci proses lain, dst) HARUS
        # dilaporkan sebagai abort yang jujur juga, bukan cuma kegagalan
        # revalidasi pre-emptive; dua-duanya sama-sama "stop safely, report
        # clearly", dan yang UDAH kehapus di iterasi-iterasi sebelumnya
        # TETAP tercatat di `deleted` (nggak bisa "dibatalkan mundur").
        try:
            revalidated = _revalidate_deletion_candidate(
                e["path"], backup_dir_resolved, newest_path=newest_path, protect=protect
            )
            meta_target = _revalidate_metadata_deletion_candidate(revalidated, backup_dir_resolved)
            revalidated.unlink()
            if meta_target is not None:
                meta_target.unlink(missing_ok=True)
        except (BackupError, OSError) as exc:
            result["deleted"] = deleted
            result["remaining_after_apply"] = [e2 for e2 in existing_sorted if e2["path"] not in {d["path"] for d in deleted}]
            result["applied"] = True
            result["aborted"] = True
            result["abort_reason"] = str(exc)
            return result

        deleted.append(e)

    result["deleted"] = deleted
    result["remaining_after_apply"] = remaining_projected
    result["applied"] = True
    return result
