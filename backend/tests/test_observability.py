"""
Test buat fondasi observability backend: endpoint /api/health, request ID
korelasi, logging terstruktur (utils/observability.py), dan respons error
yang konsisten (app.py error handlers).

SEMUA test pakai app/client fixture dari conftest.py (SQLite in-memory,
FLASK_ENV=testing) — TIDAK PERNAH menyentuh instance/tracker.db yang
sebenarnya.
"""

import logging
import os
import re
import threading

import pytest
from sqlalchemy.pool import NullPool

from app import create_app
from extensions import db
from tests.conftest import auth_headers, register
from utils.observability import REQUEST_ID_RE, resolve_app_version, resolve_request_id


@pytest.fixture
def captured_logs():
    """Nangkep LogRecord dari logger 'babytracker' langsung (bukan lewat
    caplog/root logger — logger kita propagate=False), buat diperiksa
    field-field-nya (termasuk mastiin field SENSITIF nggak ada)."""
    records = []

    class _ListHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _ListHandler()
    logger = logging.getLogger("babytracker")
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


# --------------------------------------------------------------------------
# 1-7: endpoint /api/health
# --------------------------------------------------------------------------


def test_1_healthy_database_returns_200(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_2_response_shape_is_safe(client):
    resp = client.get("/api/health")
    body = resp.get_json()
    assert set(body.keys()) == {"status", "database", "version", "request_id"}
    # nggak boleh ada field yang nyebut path/tipe/hostname/dst
    forbidden_substrings = ["sqlite", "instance", "tracker.db", "path", "hostname", ".py"]
    body_text = str(body).lower()
    for term in forbidden_substrings:
        assert term not in body_text, f"respons /api/health mengandung {term!r}: {body}"


def test_3_select_1_failure_returns_503(client, monkeypatch):
    monkeypatch.setattr("app.check_database_ok", lambda app: False)
    resp = client.get("/api/health")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"


def test_4_exception_details_are_not_exposed(client, monkeypatch):
    def _boom(app):
        raise RuntimeError("koneksi database rahasia gagal di /some/secret/path.db")

    monkeypatch.setattr("app.check_database_ok", _boom)
    resp = client.get("/api/health")
    # check_database_ok yang beneran nangkep exception-nya sendiri (lihat
    # utils/observability.py) — tapi kalau SAMPAI ada yang bocor, ini test
    # bakal ketangkep di sini juga: pesan RuntimeError di atas TIDAK BOLEH
    # muncul di mana pun pada respons akhir (baik 503 normal ATAU 500 kalau
    # sampai nembus ke global exception handler).
    assert "secret" not in resp.get_data(as_text=True)
    assert "/some/secret/path.db" not in resp.get_data(as_text=True)
    assert "RuntimeError" not in resp.get_data(as_text=True)


def test_5_version_is_sanitized(client, monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.2.3-beta")
    resp = client.get("/api/health")
    assert resp.get_json()["version"] == "1.2.3-beta"

    monkeypatch.setenv("APP_VERSION", "not safe\nvalue; rm -rf /")
    resp2 = client.get("/api/health")
    assert resp2.get_json()["version"] == "unknown"

    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.delenv("DEPLOY_COMMIT", raising=False)
    resp3 = client.get("/api/health")
    assert resp3.get_json()["version"] == "unknown"


def test_5b_resolve_app_version_rejects_overlong_value(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "a" * 200)
    assert resolve_app_version() == "unknown"


def test_6_database_path_is_never_returned(client):
    resp = client.get("/api/health")
    text = resp.get_data(as_text=True)
    assert "instance" not in text
    assert ".db" not in text
    assert os.sep not in text


def test_7_request_id_appears_in_json_and_headers(client):
    resp = client.get("/api/health")
    body_request_id = resp.get_json()["request_id"]
    header_request_id = resp.headers.get("X-Request-ID")
    assert body_request_id
    assert header_request_id
    assert body_request_id == header_request_id
    assert REQUEST_ID_RE.match(header_request_id)


# --------------------------------------------------------------------------
# 8-13: request ID korelasi
# --------------------------------------------------------------------------


def test_8_valid_incoming_request_id_is_preserved(client):
    resp = client.get("/api/health", headers={"X-Request-ID": "my-valid-id_123"})
    assert resp.headers["X-Request-ID"] == "my-valid-id_123"
    assert resp.get_json()["request_id"] == "my-valid-id_123"


def test_9_invalid_request_id_is_replaced(client):
    resp = client.get("/api/health", headers={"X-Request-ID": "has spaces and!@# symbols"})
    returned = resp.headers["X-Request-ID"]
    assert returned != "has spaces and!@# symbols"
    assert REQUEST_ID_RE.match(returned)


def test_10_overlong_request_id_is_replaced(client):
    overlong = "a" * 200
    resp = client.get("/api/health", headers={"X-Request-ID": overlong})
    returned = resp.headers["X-Request-ID"]
    assert returned != overlong
    assert len(returned) <= 64


def test_11_newline_control_character_request_id_is_rejected():
    # dites langsung di level fungsi murni-nya — Werkzeug/WSGI sendiri
    # udah nolak newline mentah di header HTTP beneran (jadi nggak bisa
    # dites lewat test_client), tapi logika pemvalidasiannya sendiri WAJIB
    # nolak walau somehow ada yang lolos sampai sini.
    assert resolve_request_id("abc\ndef") != "abc\ndef"
    assert resolve_request_id("abc\rdef") != "abc\rdef"
    assert resolve_request_id("abc\x00def") != "abc\x00def"
    assert REQUEST_ID_RE.match(resolve_request_id("abc\ndef"))


def test_12_generated_ids_are_valid(client):
    resp = client.get("/api/health")  # nggak ngasih X-Request-ID -> harus di-generate
    generated = resp.headers["X-Request-ID"]
    assert REQUEST_ID_RE.match(generated)
    assert len(generated) <= 64


@pytest.fixture
def file_db_app():
    """SQLite file sementara + NullPool — sama persis pola
    tests/test_concurrency.py, biar test konkurensi di bawah beneran pakai
    thread asli tanpa masalah locking SQLite in-memory."""
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    application = create_app(
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path}",
            "SQLALCHEMY_ENGINE_OPTIONS": {"poolclass": NullPool, "connect_args": {"check_same_thread": False}},
        }
    )
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()
    os.remove(path)


def test_13_concurrent_requests_do_not_share_request_ids(file_db_app):
    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        with file_db_app.test_client() as c:
            resp = c.get("/api/health")
            results.append(resp.headers["X-Request-ID"])

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    assert len(set(results)) == 8, f"ada request ID yang kepakai dobel: {results}"


# --------------------------------------------------------------------------
# 14-20: logging
# --------------------------------------------------------------------------


def test_14_request_completion_log_has_required_fields(client, captured_logs):
    resp = client.get("/api/health")
    completion_records = [r for r in captured_logs if getattr(r, "event", None) == "request_completed"]
    assert len(completion_records) == 1
    record = completion_records[0]

    assert record.request_id == resp.headers["X-Request-ID"]
    assert record.method == "GET"
    assert record.route == "/api/health"
    assert record.status == 200
    assert isinstance(record.duration_ms, float)


def test_15_16_17_18_authorization_cookies_body_query_absent_from_logs(client, captured_logs):
    resp = client.post(
        "/api/auth/register?debug_query_value=should-never-appear",
        json={"name": "Rahasia Nama", "email": "rahasia@example.com", "password": "supersecret123"},
        headers={"Authorization": "Bearer some-fake-token-value", "Cookie": "session=super-secret-cookie-value"},
    )
    assert resp.status_code == 201

    from utils.observability import _JsonLineFormatter

    formatter = _JsonLineFormatter()
    rendered_lines = [formatter.format(r) for r in captured_logs]
    full_text = "\n".join(rendered_lines)

    assert "some-fake-token-value" not in full_text
    assert "super-secret-cookie-value" not in full_text
    assert "supersecret123" not in full_text
    assert "rahasia@example.com" not in full_text
    assert "Rahasia Nama" not in full_text
    assert "should-never-appear" not in full_text
    assert "Authorization" not in full_text
    assert "Cookie" not in full_text


def test_19_sensitive_fields_absent_even_from_record_attributes(client, captured_logs):
    client.post(
        "/api/auth/register",
        json={"name": "Another Name", "email": "another@example.com", "password": "anothersecret"},
    )
    # `record.name` bawaan stdlib logging (nama LOGGER-nya, "babytracker")
    # itu SENGAJA nggak dicek di sini — itu bukan data user, cuma internal
    # logging Python. Yang diperiksa: nilai-nilai SENSITIF (bukan nama
    # attribute) nggak pernah nempel di attribute MANA PUN pada record.
    sensitive_values = ("Another Name", "another@example.com", "anothersecret")
    for record in captured_logs:
        for attr_name, attr_value in vars(record).items():
            for sensitive in sensitive_values:
                assert sensitive not in str(attr_value), (
                    f"LogRecord.{attr_name} = {attr_value!r} mengandung nilai sensitif {sensitive!r}"
                )


def test_20_repeated_app_creation_does_not_duplicate_handlers():
    logger = logging.getLogger("babytracker")
    before = len(logger.handlers)

    create_app()
    create_app()
    create_app()

    assert len(logger.handlers) == before or len(logger.handlers) == 1


# --------------------------------------------------------------------------
# 21-27: error handling
# --------------------------------------------------------------------------


def test_21_22_23_unexpected_exception_returns_safe_500_without_stack_trace(client, monkeypatch):
    user = register(client)

    def _boom(*args, **kwargs):
        raise RuntimeError("kegagalan internal yang nggak terduga, detail rahasia XYZ")

    monkeypatch.setattr("routes.auth_routes.get_current_user_id", _boom)

    resp = client.get("/api/auth/me", headers=auth_headers(user["token"]))

    assert resp.status_code == 500  # 21
    body = resp.get_json()
    text = resp.get_data(as_text=True)
    assert "kegagalan internal" not in text  # 22 — pesan exception asli nggak bocor
    assert "Traceback" not in text
    assert "RuntimeError" not in text
    assert body == {
        "error": {
            "code": "internal_error",
            "message": "Terjadi kesalahan pada server.",
            "request_id": resp.headers["X-Request-ID"],
        }
    }
    assert body["error"]["request_id"] == resp.headers["X-Request-ID"]  # 23


def test_24_existing_validation_status_unchanged(client):
    # register dengan field kosong — respons LAMA (flat {"error": "..."}), BUKAN dibungkus baru
    resp = client.post("/api/auth/register", json={"name": "", "email": "", "password": ""})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "Nama, email, dan password wajib diisi"}


def test_25_existing_authentication_behavior_unchanged(client):
    resp = client.post("/api/auth/login", json={"email": "notfound@example.com", "password": "whatever123"})
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "Email atau password salah"}


def test_27_cors_headers_remain_present(client, monkeypatch):
    origin = "http://localhost:5173"
    ok_resp = client.get("/api/health", headers={"Origin": origin})
    assert "Access-Control-Allow-Origin" in ok_resp.headers

    monkeypatch.setattr("app.check_database_ok", lambda app: False)
    degraded_resp = client.get("/api/health", headers={"Origin": origin})
    assert "Access-Control-Allow-Origin" in degraded_resp.headers

    user = register(client)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("routes.auth_routes.get_current_user_id", _boom)
    error_resp = client.get("/api/auth/me", headers={**auth_headers(user["token"]), "Origin": origin})
    assert error_resp.status_code == 500
    assert "Access-Control-Allow-Origin" in error_resp.headers


def test_404_uses_standardized_error_shape(client):
    resp = client.get("/api/this-route-does-not-exist")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == resp.headers["X-Request-ID"]


def test_405_uses_standardized_error_shape(client):
    resp = client.delete("/api/health")
    assert resp.status_code == 405
    body = resp.get_json()
    assert body["error"]["code"] == "method_not_allowed"
