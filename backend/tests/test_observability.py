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
import sqlite3
import threading
import time

import pytest
from sqlalchemy.pool import NullPool

from app import create_app
from extensions import db
from tests.conftest import TEST_FRONTEND_ORIGIN, auth_headers, create_child, register
from utils.observability import (
    REQUEST_ID_RE,
    check_database_ok,
    resolve_app_version,
    resolve_request_id,
)


def make_file_app(db_path):
    """create_app() nunjuk ke file SQLite sementara (bukan in-memory) —
    dibutuhkan buat test check_database_ok yang beneran nguji jalur
    sqlite3 mentah + busy_timeout (lihat utils/observability.py), yang
    SENGAJA cuma aktif buat database berbasis file (jalur in-memory dipakai
    fixture client/app biasa dari conftest.py)."""
    return create_app(config_overrides={"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"})


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
    monkeypatch.setattr("app.check_database_ok", lambda app: (False, "error"))
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
    origin = TEST_FRONTEND_ORIGIN
    ok_resp = client.get("/api/health", headers={"Origin": origin})
    assert "Access-Control-Allow-Origin" in ok_resp.headers

    monkeypatch.setattr("app.check_database_ok", lambda app: (False, "error"))
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


# --------------------------------------------------------------------------
# Isu 1 — health check dibatasi genuine (bukan thread-per-request yang
# nunggu worker macet selesai lewat executor.shutdown(wait=True))
# --------------------------------------------------------------------------


def test_healthy_file_database_check_succeeds(tmp_path):
    app = make_file_app(tmp_path / "health.db")
    ok, category = check_database_ok(app)
    assert ok is True
    assert category is None


def test_database_exception_returns_degraded_with_error_category(tmp_path):
    db_path = tmp_path / "health.db"
    app = make_file_app(db_path)
    with app.app_context():
        db.engine.dispose()
    os.remove(db_path)

    ok, category = check_database_ok(app, timeout_seconds=2.0)
    assert ok is False
    assert category == "error"


def test_locked_database_returns_within_strict_upper_bound(tmp_path):
    db_path = tmp_path / "health.db"
    app = make_file_app(db_path)

    # koneksi sqlite3 MENTAH terpisah, nahan EXCLUSIVE lock di file yang
    # SAMA — mensimulasikan database yang beneran macet/dikunci, tanpa
    # perlu mock apa pun (locking SQLite asli). EXCLUSIVE adalah lock
    # TERKUAT SQLite (lihat https://sqlite.org/lockingv3.html) — nge-blok
    # SEMUA koneksi lain yang beneran nyoba baca halaman database (lihat
    # test_health_check_query_reads_the_actual_database_not_a_constant di
    # bawah buat kenapa query pengecekannya HARUS beneran baca, bukan
    # ekspresi konstan, biar lock ini ketauan di platform manapun).
    lock_conn = sqlite3.connect(str(db_path), isolation_level=None)
    lock_conn.execute("BEGIN EXCLUSIVE;")
    try:
        timeout_seconds = 0.3
        start = time.monotonic()
        ok, category = check_database_ok(app, timeout_seconds=timeout_seconds)
        elapsed = time.monotonic() - start

        assert ok is False
        assert category == "timeout"
        # bound GENUINE: nggak pernah nunggu jauh lebih lama dari
        # timeout_seconds yang diminta (beda dari implementasi lama yang
        # bisa nunggu SAMPAI operasi macet-nya selesai sendiri, alias
        # nggak ada batas atas sama sekali). Margin longgar sengaja
        # dipakai (bukan threshold ketat) biar nggak flaky di CI yang
        # lambat, tapi tetap membuktikan ini BUKAN hang tanpa batas.
        assert elapsed < timeout_seconds + 3.0
    finally:
        lock_conn.execute("ROLLBACK;")
        lock_conn.close()


def test_repeated_timeouts_do_not_increase_live_thread_count(tmp_path):
    db_path = tmp_path / "health.db"
    app = make_file_app(db_path)

    lock_conn = sqlite3.connect(str(db_path), isolation_level=None)
    lock_conn.execute("BEGIN EXCLUSIVE;")
    try:
        before = threading.active_count()
        for _ in range(5):
            ok, category = check_database_ok(app, timeout_seconds=0.2)
            assert ok is False
            assert category == "timeout"
        after = threading.active_count()
        assert after == before, (
            f"jumlah thread hidup naik dari {before} ke {after} setelah 5x "
            "timeout beruntun — health check nggak boleh ninggalin worker"
        )
    finally:
        lock_conn.execute("ROLLBACK;")
        lock_conn.close()


def test_repeated_timeouts_do_not_leak_sqlite_connections(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"
    app = make_file_app(db_path)

    # lock_conn dibikin SEBELUM spy dipasang — spy nge-patch sqlite3.connect
    # secara GLOBAL (bukan cuma referensi di dalam utils/observability.py),
    # jadi kalau lock_conn dibikin SESUDAH spy, connect() punya lock_conn
    # sendiri bakal ikut kehitung juga dan bikin totalnya kelebihan 1.
    lock_conn = sqlite3.connect(str(db_path), isolation_level=None)
    lock_conn.execute("BEGIN EXCLUSIVE;")

    _, opened_ids, closed_ids = _spy_on_sqlite_connect(monkeypatch)
    try:
        for _ in range(5):
            ok, category = check_database_ok(app, timeout_seconds=0.2)
            assert ok is False
            assert category == "timeout"
    finally:
        lock_conn.execute("ROLLBACK;")
        lock_conn.close()

    # setiap koneksi sqlite3 MENTAH yang dibuka buat pengecekan (biar
    # timeout kejadian pun) harus tetep ketutup lewat blok finally —
    # nggak ada file descriptor/koneksi yang bocor walau query-nya gagal.
    assert len(opened_ids) == 5
    assert sorted(opened_ids) == sorted(closed_ids)


def test_database_becomes_healthy_again_after_lock_is_released(tmp_path):
    db_path = tmp_path / "health.db"
    app = make_file_app(db_path)

    lock_conn = sqlite3.connect(str(db_path), isolation_level=None)
    lock_conn.execute("BEGIN EXCLUSIVE;")
    ok_while_locked, category_while_locked = check_database_ok(app, timeout_seconds=0.2)
    lock_conn.execute("ROLLBACK;")
    lock_conn.close()

    assert ok_while_locked is False
    assert category_while_locked == "timeout"

    ok_after_release, category_after_release = check_database_ok(app)
    assert ok_after_release is True
    assert category_after_release is None


def test_health_endpoint_timeout_is_safe_in_response_and_logged_as_category(client, captured_logs, monkeypatch):
    monkeypatch.setattr("app.check_database_ok", lambda app: (False, "timeout"))

    resp = client.get("/api/health")

    assert resp.status_code == 503
    assert resp.get_json() == {
        "status": "degraded",
        "database": "unavailable",
        "request_id": resp.headers["X-Request-ID"],
    }
    # kategori kegagalan TIDAK PERNAH ikut ke respons klien — cuma masuk
    # log server-side (diperiksa di bawah)
    assert "timeout" not in resp.get_data(as_text=True).lower()

    completion_records = [r for r in captured_logs if getattr(r, "event", None) == "request_completed"]
    assert len(completion_records) == 1
    assert completion_records[0].db_check_category == "timeout"


def _spy_on_sqlite_connect(monkeypatch, target="utils.observability.sqlite3.connect"):
    """
    sqlite3.Connection adalah tipe C-extension — nggak bisa nge-timpa
    atribut instance-nya langsung (mis. `conn.execute = ...`), jadi
    spy-nya lewat subclass Connection yang di-pass ke `factory=`
    (mekanisme resmi yang didukung modul sqlite3 buat kasus ini). Dipakai
    bareng buat nge-track statement yang dieksekusi DAN buat nge-track
    connect()/close() (lihat test kebocoran koneksi di bawah).
    """
    executed_statements = []
    opened_ids = []
    closed_ids = []
    original_connect = sqlite3.connect

    class _SpyConnection(sqlite3.Connection):
        def execute(self, sql, *a, **k):
            executed_statements.append(sql)
            return super().execute(sql, *a, **k)

        def close(self):
            closed_ids.append(id(self))
            return super().close()

    def spy_connect(*args, **kwargs):
        kwargs["factory"] = _SpyConnection
        conn = original_connect(*args, **kwargs)
        opened_ids.append(id(conn))
        return conn

    monkeypatch.setattr(target, spy_connect)
    return executed_statements, opened_ids, closed_ids


def test_health_check_query_reads_the_actual_database_not_a_constant(tmp_path, monkeypatch):
    """
    Isu 2 (korektif): `SELECT 1` tanpa FROM clause diverifikasi EMPIRIS
    bisa dieksekusi SQLite TANPA pernah nyoba ambil lock (nggak nyentuh
    halaman database manapun) — jadi nggak pernah BENERAN membuktikan
    database-nya kebaca, dan nggak reliably ketauan kalau database-nya
    lagi dikunci koneksi lain (root cause 2 test gagal di PythonAnywhere
    Linux, meski lolos di Windows). Query-nya sekarang HARUS baca
    `sqlite_master` (tabel sistem yang selalu ada, termasuk di database
    kosong) biar SQLite genuinely acquire SHARED lock.
    """
    db_path = tmp_path / "health.db"
    app = make_file_app(db_path)

    executed_statements, opened_ids, closed_ids = _spy_on_sqlite_connect(monkeypatch)

    ok, category = check_database_ok(app)

    assert ok is True
    assert category is None
    # PRAGMA busy_timeout doang yang boleh nyelip di samping query
    # baca-nya sendiri — bukan pengecekan integritas apa pun.
    assert not any("integrity_check" in s.lower() for s in executed_statements)
    assert not any(s.strip().lower() == "select 1;" for s in executed_statements)
    read_statements = [s for s in executed_statements if "pragma" not in s.lower()]
    assert len(read_statements) == 1
    assert "sqlite_master" in read_statements[0].lower()
    assert "from" in read_statements[0].lower()
    # 1 koneksi dibuka, 1 koneksi ditutup — nggak ada yang bocor
    assert opened_ids == closed_ids


# --------------------------------------------------------------------------
# Isu 2 — log exception nggak ketangkep TIDAK PERNAH ngandung pesan
# exception mentah / str(exc) / traceback mentah secara default
# --------------------------------------------------------------------------


_SENSITIVE_MARKERS = (
    "SuperSecretPass123",
    "Bearer.fake.jwt.token.value",
    "rahasia@example.com",
    "Kiran Mustika",
    "alergi susu sapi, dosis amoxicillin 5ml",
    "SELECT * FROM users WHERE email",
    "params=('rahasia@example.com', 'SuperSecretPass123')",
)


def test_unhandled_exception_message_never_appears_anywhere_in_logs(client, captured_logs, monkeypatch):
    user = register(client)
    secret_message = (
        "password=SuperSecretPass123 token=Bearer.fake.jwt.token.value "
        "user=rahasia@example.com baby=Kiran Mustika notes='alergi susu sapi, "
        "dosis amoxicillin 5ml' sql=\"SELECT * FROM users WHERE email = ?\" "
        "params=('rahasia@example.com', 'SuperSecretPass123') "
        f"db_path={os.path.join('C:', os.sep, 'Users', 'opname', 'baby-daily-tracker', 'backend', 'instance', 'tracker.db')}"
    )

    def _boom(*args, **kwargs):
        raise RuntimeError(secret_message)

    monkeypatch.setattr("routes.auth_routes.get_current_user_id", _boom)
    resp = client.get("/api/auth/me", headers=auth_headers(user["token"]))
    assert resp.status_code == 500

    from utils.observability import _JsonLineFormatter

    full_text = "\n".join(_JsonLineFormatter().format(r) for r in captured_logs)

    assert secret_message not in full_text
    for marker in _SENSITIVE_MARKERS:
        assert marker not in full_text, f"marker sensitif {marker!r} nyelip ke log"
    assert "tracker.db" not in full_text
    assert "opname" not in full_text

    # field yang MEMANG boleh/harus ada tetap ada
    assert "RuntimeError" in full_text
    assert resp.headers["X-Request-ID"] in full_text

    error_records = [r for r in captured_logs if getattr(r, "event", None) == "unhandled_exception"]
    assert len(error_records) == 1
    record = error_records[0]
    # default: exc_info nggak pernah diisi True -> nggak ada stack_trace mentah
    assert not record.exc_info
    assert isinstance(record.frames, list)
    assert len(record.frames) > 0
    for frame in record.frames:
        assert set(frame.keys()) == {"file", "function", "line"}
        assert not os.path.isabs(frame["file"])


def test_unhandled_exception_log_route_uses_safe_template(client, captured_logs, monkeypatch):
    user = register(client)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("routes.auth_routes.get_current_user_id", _boom)
    client.get("/api/auth/me", headers=auth_headers(user["token"]))

    error_records = [r for r in captured_logs if getattr(r, "event", None) == "unhandled_exception"]
    assert len(error_records) == 1
    assert error_records[0].route == "/api/auth/me"


def test_raw_traceback_config_defaults_to_false_and_is_not_tied_to_debug(monkeypatch):
    monkeypatch.delenv("OBSERVABILITY_LOG_RAW_TRACEBACKS", raising=False)
    app = create_app()
    # TestConfig punya DEBUG=True, tapi flag traceback mentah TETAP False —
    # membuktikan ini nggak "nempel"/ngikutin DEBUG sama sekali.
    assert app.config.get("DEBUG") is True
    assert app.config["OBSERVABILITY_LOG_RAW_TRACEBACKS"] is False


def test_raw_traceback_opt_in_still_never_leaks_to_client_response(monkeypatch):
    app = create_app(config_overrides={"OBSERVABILITY_LOG_RAW_TRACEBACKS": True})
    client = app.test_client()

    def _boom(*args, **kwargs):
        raise RuntimeError("pesan rahasia harus tetap gak nongol di respons klien")

    monkeypatch.setattr("routes.auth_routes.get_current_user_id", _boom)
    user = register(client)
    resp = client.get("/api/auth/me", headers=auth_headers(user["token"]))

    assert resp.status_code == 500
    assert "pesan rahasia" not in resp.get_data(as_text=True)
    assert resp.get_json() == {
        "error": {
            "code": "internal_error",
            "message": "Terjadi kesalahan pada server.",
            "request_id": resp.headers["X-Request-ID"],
        }
    }


# --------------------------------------------------------------------------
# Isu 3 — path yang nggak match route apa pun nggak pernah ditulis mentah
# ke log (safe_route_template())
# --------------------------------------------------------------------------


def test_matched_dynamic_route_logs_only_its_template(client, captured_logs):
    user = register(client)
    child = create_child(client, user["token"])

    resp = client.get(f"/api/children/{child['id']}", headers=auth_headers(user["token"]))
    assert resp.status_code == 200

    completion_records = [
        r for r in captured_logs
        if getattr(r, "event", None) == "request_completed" and getattr(r, "method", None) == "GET"
    ]
    matching = [r for r in completion_records if r.route == "/api/children/<int:child_id>"]
    assert len(matching) == 1
    assert str(child["id"]) not in matching[0].route


def test_unmatched_secret_like_path_logs_only_the_safe_constant(client, captured_logs):
    resp = client.get("/api/reset/token-secret-value?leak=should-not-appear")
    assert resp.status_code == 404

    completion_records = [r for r in captured_logs if getattr(r, "event", None) == "request_completed"]
    assert len(completion_records) == 1
    record = completion_records[0]
    assert record.route == "<unmatched>"

    from utils.observability import _JsonLineFormatter

    full_text = _JsonLineFormatter().format(record)
    assert "token-secret-value" not in full_text
    assert "leak" not in full_text
    assert "should-not-appear" not in full_text
    assert "/api/reset/" not in full_text


def test_error_logs_use_the_same_normalized_route_logic(client, captured_logs, monkeypatch):
    user = register(client)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("routes.auth_routes.get_current_user_id", _boom)
    client.get("/api/auth/me", headers=auth_headers(user["token"]))

    error_records = [r for r in captured_logs if getattr(r, "event", None) == "unhandled_exception"]
    assert len(error_records) == 1
    # sama persis mekanisme yang dipakai request_completed (matched route
    # template) — bukan request.path mentah
    assert error_records[0].route == "/api/auth/me"


# --------------------------------------------------------------------------
# Isu 4 — X-Request-ID lengkap di CORS (allow + expose), lintas origin
#
# SEMUA test di bagian ini pakai fixture `client` (lewat `app` di
# conftest.py), yang sekarang tergantung ke fixture `frontend_origin_env`
# — itu maksa FRONTEND_ORIGIN ke TEST_FRONTEND_ORIGIN (dideklarasikan di
# conftest.py, di-reuse di sini biar 1 sumber kebenaran doang) SEBELUM
# create_app() dipanggil, TERLEPAS dari environment host (mis.
# PythonAnywhere yang FRONTEND_ORIGIN aslinya nunjuk ke origin Vercel
# staging beneran, bukan localhost — itu akar masalah kenapa 8 test CORS
# ini gagal di sana sebelumnya, meski lolos di mesin dev Windows yang
# kebetulan .env-nya nyantumin localhost). monkeypatch.setenv otomatis
# balikin env var ini ke nilai semula begitu tiap test kelar.
# --------------------------------------------------------------------------

_FRONTEND_ORIGIN = TEST_FRONTEND_ORIGIN


def test_preflight_allows_x_request_id_header(client):
    resp = client.open(
        "/api/health",
        method="OPTIONS",
        headers={
            "Origin": _FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Request-ID",
        },
    )
    allow_headers = resp.headers.get("Access-Control-Allow-Headers", "").lower()
    assert "x-request-id" in allow_headers


def test_preflight_still_allows_existing_headers(client):
    resp = client.open(
        "/api/health",
        method="OPTIONS",
        headers={
            "Origin": _FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization, X-Idempotency-Key, Content-Type",
        },
    )
    allow_headers = resp.headers.get("Access-Control-Allow-Headers", "").lower()
    for expected in ("authorization", "x-idempotency-key", "content-type"):
        assert expected in allow_headers


def test_preflight_response_itself_carries_cors_origin_header(client):
    resp = client.open(
        "/api/health",
        method="OPTIONS",
        headers={
            "Origin": _FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Request-ID",
        },
    )
    assert resp.headers.get("Access-Control-Allow-Origin") == _FRONTEND_ORIGIN


def test_successful_response_exposes_x_request_id_header(client):
    resp = client.get("/api/health", headers={"Origin": _FRONTEND_ORIGIN})
    expose_headers = resp.headers.get("Access-Control-Expose-Headers", "").lower()
    assert "x-request-id" in expose_headers


def test_degraded_response_exposes_x_request_id_header(client, monkeypatch):
    monkeypatch.setattr("app.check_database_ok", lambda app: (False, "error"))
    resp = client.get("/api/health", headers={"Origin": _FRONTEND_ORIGIN})
    assert resp.status_code == 503
    expose_headers = resp.headers.get("Access-Control-Expose-Headers", "").lower()
    assert "x-request-id" in expose_headers


def test_unexpected_500_response_exposes_x_request_id_header(client, monkeypatch):
    user = register(client)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("routes.auth_routes.get_current_user_id", _boom)
    resp = client.get("/api/auth/me", headers={**auth_headers(user["token"]), "Origin": _FRONTEND_ORIGIN})

    assert resp.status_code == 500
    expose_headers = resp.headers.get("Access-Control-Expose-Headers", "").lower()
    assert "x-request-id" in expose_headers


def test_unapproved_origin_does_not_get_cors_access(client):
    resp = client.get("/api/health", headers={"Origin": "https://evil.example.com"})
    assert resp.status_code == 200  # CORS ditegakkan browser, bukan server — route tetep jalan
    acao = resp.headers.get("Access-Control-Allow-Origin")
    assert acao != "https://evil.example.com"
    assert acao != "*"


def test_credentials_support_and_no_wildcard_origin_unchanged(client):
    resp = client.get("/api/health", headers={"Origin": _FRONTEND_ORIGIN})
    assert resp.headers.get("Access-Control-Allow-Credentials") == "true"
    assert resp.headers.get("Access-Control-Allow-Origin") != "*"
    assert resp.headers.get("Access-Control-Allow-Origin") == _FRONTEND_ORIGIN


def test_cors_tests_unaffected_by_preexisting_pythonanywhere_style_env_var(monkeypatch):
    """
    Regresi eksplisit buat skenario yang bikin 8 test CORS gagal di
    PythonAnywhere: environment HOST udah punya FRONTEND_ORIGIN ke-set
    ke origin Vercel staging beneran SEBELUM app dibikin. Fixture
    terpusat (`frontend_origin_env` di conftest.py) HARUS menang di atas
    nilai host apa pun — dites langsung di sini (bukan lewat fixture
    `client`) biar urutan "host env ke-set duluan, baru di-override"-nya
    eksplisit dan nggak bergantung urutan resolusi fixture pytest.
    """
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://baby-tracker-staging.vercel.app")
    # ...meniru persis apa yang dilakuin fixture frontend_origin_env:
    # override SEBELUM create_app() dipanggil.
    monkeypatch.setenv("FRONTEND_ORIGIN", TEST_FRONTEND_ORIGIN)

    app = create_app()
    client = app.test_client()
    resp = client.get("/api/health", headers={"Origin": TEST_FRONTEND_ORIGIN})

    assert resp.headers.get("Access-Control-Allow-Origin") == TEST_FRONTEND_ORIGIN
    assert resp.headers.get("Access-Control-Allow-Credentials") == "true"


def test_non_default_configured_origin_is_honored(monkeypatch):
    """
    Bukti eksplisit kalau CORS-nya beneran BACA FRONTEND_ORIGIN (bukan
    hardcode ke localhost di suatu tempat): pakai origin Vercel-style
    yang BUKAN default/localhost sama sekali, konfigurasi app langsung
    (bukan fixture `client` yang udah dikunci ke TEST_FRONTEND_ORIGIN),
    dan buktiin origin itu yang dapet akses CORS — origin default/test
    yang LAIN justru harus DITOLAK di app yang sama.
    """
    custom_origin = "https://baby-tracker-staging.vercel.app"
    monkeypatch.setenv("FRONTEND_ORIGIN", custom_origin)

    app = create_app()
    client = app.test_client()

    resp = client.get("/api/health", headers={"Origin": custom_origin})
    assert resp.headers.get("Access-Control-Allow-Origin") == custom_origin
    assert resp.headers.get("Access-Control-Allow-Credentials") == "true"

    other_resp = client.get("/api/health", headers={"Origin": TEST_FRONTEND_ORIGIN})
    acao = other_resp.headers.get("Access-Control-Allow-Origin")
    assert acao != TEST_FRONTEND_ORIGIN
    assert acao != "*"
