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

Stack trace BOLEH masuk log SERVER-SIDE (buat debugging) lewat baris log
`unhandled_exception` yang terpisah dari log ringkasan request biasa —
tapi TIDAK PERNAH dikembalikan ke klien.
"""

import json
import logging
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from flask import g, jsonify, request
from sqlalchemy import text
from werkzeug.exceptions import HTTPException

LOGGER_NAME = "babytracker"

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
        # stack trace CUMA nempel di sini kalau caller eksplisit ngasih
        # exc_info=True (lihat handle_unexpected_exception di bawah) — log
        # ringkasan request biasa TIDAK PERNAH lewat jalur ini.
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

        route = request.url_rule.rule if request.url_rule else request.path

        extra = {
            "event": "request_completed",
            "request_id": request_id,
            "method": request.method,
            "route": route,
            "status": response.status_code,
        }
        if duration_ms is not None:
            extra["duration_ms"] = duration_ms
        exception_type = getattr(g, "exception_type", None)
        if exception_type is not None:
            extra["exception_type"] = exception_type
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

        try:
            logger.error(
                "unhandled_exception",
                exc_info=True,
                extra={
                    "event": "unhandled_exception",
                    "request_id": getattr(g, "request_id", None) or "unknown",
                    "method": request.method,
                    "route": request.url_rule.rule if request.url_rule else request.path,
                    "exception_type": exception_type,
                },
            )
        except Exception:
            pass

        body = _build_error_body("internal_error", "Terjadi kesalahan pada server.")
        return jsonify(body), 500


# --------------------------------------------------------------------------
# Pengecekan kesehatan database — RINGAN (SELECT 1), BUKAN integrity_check
# penuh (itu cuma buat script diagnostik manual, lihat scripts/
# production_health_check.py). Dibungkus timeout pendek di thread terpisah
# biar 1 permintaan /api/health nggak bisa nge-hang lama walau DB-nya
# somehow macet.
# --------------------------------------------------------------------------

DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS = 2.0


def check_database_ok(app, timeout_seconds=DEFAULT_HEALTH_CHECK_TIMEOUT_SECONDS):
    from extensions import db

    def _run():
        with app.app_context():
            db.session.execute(text("SELECT 1"))
            db.session.remove()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(_run).result(timeout=timeout_seconds)
        return True
    except Exception:
        return False
