"""
Fondasi observability backend: request ID korelasi, logging terstruktur
(JSON per baris), respons error yang konsisten, dan pengecekan kesehatan
database yang ringan.

ATURAN PRIVASI KETAT — modul ini TIDAK PERNAH mencatat/mengembalikan:
  - header Authorization, cookie, isi body request/response
  - nilai query string, password, token
  - nama user/email, nama bayi, catatan bebas, nama obat, nama file upload
  - chat ID Telegram, error database mentah, stack trace ke KLIEN
  - path database, tipe database, nama tabel, jumlah record, hostname,
    environment variable, git remote/branch
  - path filesystem absolut, pesan exception mentah (`str(exc)`), teks
    traceback mentah, statement SQL, parameter SQL, request path mentah
    buat route yang nggak match

SECARA DEFAULT, log server-side TIDAK PERNAH ngandung pesan exception atau
traceback mentah — cuma tipe exception + lokasi frame yang udah disaring
(file relatif ke folder backend, nama fungsi, nomor baris — lihat
`_safe_traceback_frames`). Traceback mentah HANYA bisa nyala lewat config
eksplisit `OBSERVABILITY_LOG_RAW_TRACEBACKS` (bukan `DEBUG`/`FLASK_ENV`,
biar nggak ke-aktifin nggak sengaja di staging), default False, dan bahkan
kalau nyala TETAP cuma masuk log server — TIDAK PERNAH ke respons klien.
"""

import json
import logging
import os
import re
import sqlite3
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import g, jsonify, request
from sqlalchemy import text
from werkzeug.exceptions import HTTPException

LOGGER_NAME = "babytracker"

# backend/utils/observability.py -> dirname 2x = backend/ — dipakai buat
# nge-relatif-in path frame traceback (lihat _safe_traceback_frames) DAN
# buat resolve path database SQLite relatif (lihat
# _resolve_sqlite_health_check_path), biar nggak ada path absolut yang
# nempel di log atau di query resolusi database.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --------------------------------------------------------------------------
# Request ID
# --------------------------------------------------------------------------

# Cuma huruf/angka/hyphen/underscore, maksimal 64 karakter — SENGAJA nggak
# ada wildcard apa pun (bukan cuma "reject newline", tapi WHITELIST ketat)
# biar nggak mungkin dipakai buat log injection (newline/control character)
# ataupun query string aneh-aneh nyelip lewat header ini.
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def resolve_request_id(raw_header_value):
    """
    Terima request ID dari klien HANYA kalau formatnya cocok whitelist di
    atas — selain itu (kosong, kepanjangan, ada karakter aneh/newline/
    kontrol) selalu bikin ID baru. Request ID ini BUKAN mekanisme
    autentikasi/otorisasi apa pun — cuma buat korelasi log.
    """
    if raw_header_value and REQUEST_ID_RE.match(raw_header_value):
        return raw_header_value
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Versi aplikasi (buat /api/health) — SELALU dari environment variable yang
# udah dikonfigurasi, TIDAK PERNAH manggil `git` dari dalam request handler.
# --------------------------------------------------------------------------

_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
_VERSION_ENV_VARS = ("APP_VERSION", "DEPLOY_COMMIT")


def resolve_app_version():
    for env_var in _VERSION_ENV_VARS:
        raw = (os.environ.get(env_var) or "").strip()
        if raw and _VERSION_RE.match(raw):
            return raw
    return "unknown"


# --------------------------------------------------------------------------
# Logging terstruktur (1 baris JSON per event)
# --------------------------------------------------------------------------

# Whitelist field yang boleh nempel di 1 baris log — apa pun di luar ini
# TIDAK PERNAH ditulis, meskipun ada yang lupa nge-pass lewat `extra=`.
_ALLOWED_EXTRA_FIELDS = (
    "request_id",
    "method",
    "route",
    "status",
    "duration_ms",
    "user_id",
    "exception_type",
    "frames",
    "db_check_category",
)


class _JsonLineFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
        }
        for key in _ALLOWED_EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        # stack trace MENTAH cuma nempel di sini kalau caller eksplisit
        # ngasih exc_info truthy DAN config OBSERVABILITY_LOG_RAW_TRACEBACKS
        # lagi nyala (lihat handle_unexpected_exception di bawah — default
        # exc_info=False, jadi cabang ini nggak kepakai secara default).
        # Log ringkasan request biasa TIDAK PERNAH lewat jalur ini.
        if record.exc_info:
            payload["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(app):
    """
    Setup logger JSON-per-baris SATU KALI per proses Python — dipanggil
    tiap create_app() (termasuk berkali-kali di test/reload PythonAnywhere),
    tapi handler cuma ditambahin kalau BELUM ada, biar log nggak dobel-
    tercetak tiap request setelah app dibikin ulang berkali-kali.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if not getattr(logger, "_babytracker_configured", False):
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonLineFormatter())
        logger.addHandler(handler)
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger._babytracker_configured = True
    app.babytracker_logger = logger
    return logger


_UNMATCHED_ROUTE_LABEL = "<unmatched>"


def safe_route_template():
    """
    Balikin TEMPLATE route yang match (mis.
    "/api/children/<int:child_id>/feeding-logs"), BUKAN identifier
    dinamisnya (bukan "42") dan BUKAN request.path mentah kalau nggak ada
    route yang match sama sekali.

    request.path buat request yang NGGAK match route manapun 100%
    dikontrol pengirim request — bisa aja "/api/reset/token-secret-value"
    atau "/api/user/email@example.com" — jadi TIDAK PERNAH boleh nempel
    ke log apa pun. Dipakai konsisten di log ringkasan request DAN log
    error, biar 2 jalur itu nggak bisa nyimpang.
    """
    if request.url_rule is not None:
        return request.url_rule.rule
    return _UNMATCHED_ROUTE_LABEL


def _safe_current_user_id():
    """
    User ID yang lagi login, kalau ADA dan bisa diambil dengan aman — nggak
    pernah nge-raise (kegagalan di sini nggak boleh sampai bikin logging
    ATAU response utama gagal).
    """
    try:
        from utils.auth import get_current_user_id

        return get_current_user_id()
    except Exception:
        return None


def register_request_hooks(app, logger):
    """
    1 request ID konsisten sepanjang siklus hidup 1 request (before_request
    -> route handler -> error handler kalau ada -> after_request), plus 1
    baris log ringkasan per request SETELAH response jadi (biar durasi &
    status akhirnya kebaca).
    """

    @app.before_request
    def _bt_start_request():
        g.request_id = resolve_request_id(request.headers.get("X-Request-ID"))
        g.request_start_time = time.monotonic()

    @app.after_request
    def _bt_finish_request(response):
        request_id = getattr(g, "request_id", None) or "unknown"
        response.headers["X-Request-ID"] = request_id

        start = getattr(g, "request_start_time", None)
        duration_ms = round((time.monotonic() - start) * 1000, 2) if start is not None else None

        extra = {
            "event": "request_completed",
            "request_id": request_id,
            "method": request.method,
            "route": safe_route_template(),
            "status": response.status_code,
        }
        if duration_ms is not None:
            extra["duration_ms"] = duration_ms
        exception_type = getattr(g, "exception_type", None)
        if exception_type is not None:
            extra["exception_type"] = exception_type
        # diisi endpoint /api/health (lewat g.db_check_category) kalau DB
        # check gagal — CUMA salah satu dari 2 nilai aman ("timeout"/
        # "error"), TIDAK PERNAH pesan exception mentah (lihat
        # check_database_ok di bawah).
        db_check_category = getattr(g, "db_check_category", None)
        if db_check_category is not None:
            extra["db_check_category"] = db_check_category
        user_id = _safe_current_user_id()
        if user_id is not None:
            extra["user_id"] = user_id

        try:
            logger.info("request_completed", extra=extra)
        except Exception:
            # logging nggak pernah boleh bikin response utama gagal
            pass

        return response


# --------------------------------------------------------------------------
# Respons error yang konsisten — CUMA buat error level-framework (routing
# nggak ketemu, method salah, exception nggak ketangkep, dst). Route yang
# udah eksplisit `return jsonify({"error": "..."}), status` TIDAK disentuh
# sama sekali — itu nggak pernah lewat error handler ini (lihat
# backend/docs/OBSERVABILITY.md buat batasan lengkapnya).
# --------------------------------------------------------------------------

_ERROR_CODE_NAMES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "unprocessable_entity",
    429: "too_many_requests",
}

_ERROR_MESSAGES = {
    400: "Permintaan tidak valid.",
    401: "Autentikasi diperlukan.",
    403: "Akses ditolak.",
    404: "Sumber daya tidak ditemukan.",
    405: "Metode tidak diizinkan.",
    409: "Terjadi konflik data.",
    413: "Ukuran permintaan terlalu besar.",
    422: "Data tidak dapat diproses.",
    429: "Terlalu banyak permintaan, coba lagi nanti.",
}

_DEFAULT_ERROR_MESSAGE = "Terjadi kesalahan pada permintaan."


_MAX_SAFE_TRACEBACK_FRAMES = 6


def _safe_traceback_frames(exc, max_frames=_MAX_SAFE_TRACEBACK_FRAMES):
    """
    Ringkasan traceback yang AMAN dicatat: cuma lokasi (file relatif ke
    folder backend, nama fungsi, nomor baris) buat beberapa frame
    TERAKHIR (paling deket ke titik error) — TIDAK PERNAH nyertain teks
    baris kode, pesan exception, atau nilai variabel apa pun (yang mana
    bisa aja password/token/email/nama bayi/catatan medis/statement SQL/
    parameter SQL, tergantung di mana error-nya kejadian).

    File di luar folder backend (mis. dependency di venv/site-packages)
    tetep direlatifin (nggak pernah path absolut), walau hasilnya jadi
    ada "..\\..\\" — itu masih jauh lebih aman daripada path absolut penuh
    yang bisa bocorin username OS/struktur folder server.
    """
    try:
        tb = traceback.extract_tb(exc.__traceback__)
    except Exception:
        return []

    frames = []
    for frame in tb[-max_frames:]:
        try:
            rel_path = os.path.relpath(frame.filename, BACKEND_DIR)
        except (ValueError, TypeError):
            rel_path = os.path.basename(frame.filename or "?")
        frames.append(
            {
                "file": rel_path.replace(os.sep, "/"),
                "function": frame.name,
                "line": frame.lineno,
            }
        )
    return frames


def _build_error_body(code_name, message):
    return {
        "error": {
            "code": code_name,
            "message": message,
            "request_id": getattr(g, "request_id", None) or "unknown",
        }
    }


def register_error_handlers(app, logger):
    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        status = err.code or 500
        code_name = _ERROR_CODE_NAMES.get(status, "http_error")
        message = _ERROR_MESSAGES.get(status, _DEFAULT_ERROR_MESSAGE)
        body = _build_error_body(code_name, message)
        return jsonify(body), status

    @app.errorhandler(Exception)
    def handle_unexpected_exception(err):
        # HTTPException juga subclass Exception, tapi Flask selalu milih
        # handler yang PALING SPESIFIK di MRO — handler di atas (khusus
        # HTTPException) yang bakal kepanggil buat itu, bukan yang ini.
        exception_type = type(err).__name__
        g.exception_type = exception_type  # ikut ke log ringkasan request lewat after_request

        # Traceback MENTAH (isinya pesan exception asli — bisa aja SQL,
        # parameter SQL, path database, data user) CUMA disertain kalau
        # operator SENGAJA nyalain config ini secara eksplisit — BUKAN
        # otomatis ikut app.debug/FLASK_ENV, biar nggak ke-aktifin nggak
        # sengaja di staging/production. Default-nya False di mana pun
        # (lihat app.py:create_app). Kalau nyala pun, itu CUMA masuk log
        # SERVER-SIDE — nggak pernah ke respons klien (lihat body di bawah).
        include_raw_traceback = bool(app.config.get("OBSERVABILITY_LOG_RAW_TRACEBACKS", False))

        try:
            logger.error(
                "unhandled_exception",
                exc_info=include_raw_traceback,
                extra={
                    "event": "unhandled_exception",
                    "request_id": getattr(g, "request_id", None) or "unknown",
                    "method": request.method,
                    "route": safe_route_template(),
                    "exception_type": exception_type,
                    "frames": _safe_traceback_frames(err),
                },
            )
        except Exception:
            pass

        body = _build_error_body("internal_error", "Terjadi kesalahan pada server.")
        return jsonify(body), 500


# --------------------------------------------------------------------------
# Pengecekan kesehatan database — RINGAN (SELECT 1), BUKAN integrity_check
# penuh (itu cuma buat script diagnostik manual, lihat scripts/
# production_health_check.py).
#
# DIRANCANG KHUSUS buat deployment SQLite backend ini (lihat config.py —
# SQLALCHEMY_DATABASE_URI SELALU SQLite file lokal di production/staging
# PythonAnywhere, nggak pernah driver lain). Bound waktu di sini datang
# dari `timeout=` SQLite (busy_timeout) LEVEL DRIVER/C, BUKAN dari
# cancel/kill thread Python — sebelumnya implementasi ini pakai
# ThreadPoolExecutor(max_workers=1).submit(...).result(timeout=...), yang
# kalau timeout kejadian, `with ThreadPoolExecutor(...)` di baris
# berikutnya bakal manggil executor.shutdown(wait=True) yang NUNGGU
# worker yang macet itu SAMPAI SELESAI — jadi /api/health tetep bisa
# nge-hang selama operasi DB-nya macet, persis kebalikan dari tujuan
# timeout itu sendiri. Versi ini SAMA SEKALI nggak bikin thread baru buat
# health check biasa: query "SELECT 1" jalan sinkron di thread request
# yang sama, dibatasi busy_timeout SQLite bawaan — kalau limitnya
# kelewat, sqlite3 sendiri yang raise OperationalError (bukan Python yang
# nge-cancel apa pun), jadi TIDAK ADA sisa worker yang nyangkut di
# background, TIDAK ADA thread yang dibikin per-request (jadi TIDAK ADA
# cara buat request /api/health yang bertubi-tubi bikin jumlah thread
# nambah terus) — resource bound-nya otomatis, bukan lewat pool.
#
# Kalau suatu saat aplikasi ini pindah ke database non-SQLite, bound
# genuine kayak gini butuh dirancang ulang lewat mekanisme driver yang
# sesuai (mis. `statement_timeout` Postgres) — jangan asal pasang balik
# ThreadPoolExecutor buat "generalize"-nya, itu yang bikin bug ini ada.
# --------------------------------------------------------------------------

DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS = 2.0

# 2 SATU-SATUNYA kategori kegagalan yang boleh nempel ke log/g.* — dipilih
# lewat SEBERAPA LAMA pengecekan berlangsung sebelum gagal (bukan lewat
# parsing pesan exception-nya), biar penentuannya sendiri nggak pernah
# butuh nyimpen/ngutak-atik teks exception mentah di mana pun.
_HEALTH_CHECK_CATEGORY_TIMEOUT = "timeout"
_HEALTH_CHECK_CATEGORY_ERROR = "error"


def _resolve_sqlite_health_check_path(app):
    """
    Path file SQLite yang lagi dikonfigurasi app ini, TANPA nyentuh
    connection pool Flask-SQLAlchemy (beda dari
    scripts/db_backup_common.py:resolve_active_sqlite_path, yang sengaja
    manggil db.engine.dispose() — cocok buat backup/restore manual, TAPI
    KEBERATAN buat dipanggil di hot path publik /api/health karena bakal
    nutup koneksi idle yang lagi dipakai request lain).

    Balikin None kalau databasenya bukan SQLite berbasis file (mis.
    in-memory — SELALU kejadian di test suite, lihat config.py:TestConfig
    — production/staging SELALU file-based).
    """
    from extensions import db

    with app.app_context():
        url = db.engine.url

    drivername = (url.drivername or "").lower()
    if not drivername.startswith("sqlite"):
        return None

    database = url.database
    if not database or database == ":memory:" or database.startswith("file::memory:"):
        return None

    path = Path(database)
    if not path.is_absolute():
        path = Path(BACKEND_DIR) / path
    return path.resolve()


def _sqlite_select_1_bounded(db_path, timeout_seconds):
    """
    1 koneksi sqlite3 MENTAH (bukan lewat pool Flask-SQLAlchemy),
    read-only, PENDEK UMURNYA: connect -> SELECT 1 -> close, nggak lebih.
    `timeout=` di sini diteruskan jadi busy_timeout SQLite BENERAN (level
    driver/C) — kalau file lagi dikunci koneksi lain, SQLite RETRY
    otomatis sampai maksimal `timeout_seconds` baru raise
    OperationalError. Genuine bound dari driver, BUKAN thread yang
    di-cancel dari Python.
    """
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=timeout_seconds)
    try:
        conn.execute("SELECT 1;")
    finally:
        conn.close()


def check_database_ok(app, timeout_seconds=DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS):
    """
    Balikin (ok: bool, category: str | None).

    `category` cuma diisi kalau ok=False, dan CUMA salah satu dari 2 nilai
    aman di atas ("timeout"/"error") — TIDAK PERNAH pesan exception
    mentah, str(exc), atau apa pun yang berasal dari isi exception-nya.
    Ditentukan lewat SEBERAPA LAMA pengecekan berlangsung relatif ke
    `timeout_seconds` (elapsed >= timeout_seconds -> "timeout", lebih
    cepat dari itu -> "error" — mis. file nggak ada/rusak/config salah,
    yang gagalnya cepat, bukan nunggu lock).
    """
    start = time.monotonic()
    try:
        db_path = _resolve_sqlite_health_check_path(app)
        if db_path is not None:
            _sqlite_select_1_bounded(db_path, timeout_seconds)
        else:
            # In-memory SQLite (test suite doang, lihat docstring di
            # atas) -- nggak ada lock antar-koneksi yang mungkin
            # kejadian, jadi query langsung lewat session ORM (nggak
            # butuh wrapper tambahan; nggak ada skenario "macet" yang
            # genuine buat database yang cuma ada di 1 proses memory).
            from extensions import db

            with app.app_context():
                db.session.execute(text("SELECT 1"))
                db.session.remove()
        return True, None
    except Exception:
        elapsed = time.monotonic() - start
        category = (
            _HEALTH_CHECK_CATEGORY_TIMEOUT
            if elapsed >= timeout_seconds
            else _HEALTH_CHECK_CATEGORY_ERROR
        )
        return False, category
