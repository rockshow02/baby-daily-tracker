"""
Test buat scripts/post_deploy_smoke_test.py.

Kebanyakan test di sini memonkeypatch `requests.get` di dalam modul script
(TIDAK PERNAH request jaringan beneran ke domain eksternal) — kecuali 1 test
end-to-end (test_46_*) yang jalanin server Flask dev beneran di 127.0.0.1
port ephemeral, pakai database SQLite SEMENTARA (tempfile), buat mastiin
seluruh alur request->parse->laporan beneran nyambung, bukan cuma logic
internal terisolasi. Script yang diuji di sini TIDAK PERNAH memanggil
apa pun selain GET /health — lihat test_54_* buat penegasan eksplisitnya.
"""

import os
import sys
import tempfile
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(BACKEND_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from app import create_app  # noqa: E402

import post_deploy_smoke_test as pdst  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=200, headers=None, json_data=None, json_error=None, is_redirect=False):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data
        self._json_error = json_error
        self.is_redirect = is_redirect

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_data


# --------------------------------------------------------------------------
# fixture buat test end-to-end: server Flask dev beneran, DB SQLite sementara
# --------------------------------------------------------------------------


@pytest.fixture
def live_health_server(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "smoke-test-1.0.0")
    workdir = tempfile.mkdtemp(prefix="smoke-test-server-")
    db_path = Path(workdir) / "smoke.db"
    app = create_app(config_overrides={"SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}"})

    server = make_server("127.0.0.1", 0, app)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/api"
    finally:
        server.shutdown()
        thread.join(timeout=5)


# --------------------------------------------------------------------------
# 46: respons health yang valid -> semua pengecekan lolos (end-to-end)
# --------------------------------------------------------------------------


def test_46_valid_health_response_passes_end_to_end(live_health_server):
    report = pdst.run(live_health_server, timeout_seconds=5, max_response_ms=3000, allow_cross_host_redirect=False)

    by_name = {r.name: r for r in report.results}
    assert by_name["http_status"].status == pdst.STATUS_OK
    assert by_name["content_type"].status == pdst.STATUS_OK
    assert by_name["json_body"].status == pdst.STATUS_OK
    assert by_name["health_shape"].status == pdst.STATUS_OK
    assert by_name["database_field"].status == pdst.STATUS_OK
    assert by_name["request_id_header"].status == pdst.STATUS_OK
    assert report.exit_code() == 0


# --------------------------------------------------------------------------
# 47: timeout -> gagal dengan aman, bukan exception mentah yang nembus
# --------------------------------------------------------------------------


def test_47_timeout_fails_safely(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise pdst.requests.exceptions.Timeout()

    monkeypatch.setattr(pdst.requests, "get", raise_timeout)

    report = pdst.run("https://example.test/api", 1, 3000, False)

    by_name = {r.name: r for r in report.results}
    assert by_name["http_request"].status == pdst.STATUS_FAILED
    assert report.exit_code() == 1


# --------------------------------------------------------------------------
# 48: body bukan JSON valid -> gagal, bukan crash saat parsing
# --------------------------------------------------------------------------


def test_48_invalid_json_body_fails(monkeypatch):
    resp = FakeResponse(status_code=200, headers={"Content-Type": "application/json"}, json_error=ValueError("bad json"))
    monkeypatch.setattr(pdst.requests, "get", lambda *a, **k: resp)

    report = pdst.run("https://example.test/api", 5, 3000, False)

    by_name = {r.name: r for r in report.results}
    assert by_name["json_body"].status == pdst.STATUS_FAILED
    assert report.exit_code() == 1


# --------------------------------------------------------------------------
# 49: redirect ke host LAIN ditolak (default, tanpa --allow-cross-host-redirect)
# --------------------------------------------------------------------------


def test_49_cross_host_redirect_is_rejected(monkeypatch):
    resp = FakeResponse(
        status_code=302,
        headers={"Location": "https://evil.example.com/api/health"},
        is_redirect=True,
    )
    monkeypatch.setattr(pdst.requests, "get", lambda *a, **k: resp)

    report = pdst.run("https://example.test/api", 5, 3000, allow_cross_host_redirect=False)

    by_name = {r.name: r for r in report.results}
    assert by_name["no_unexpected_redirect"].status == pdst.STATUS_FAILED
    assert report.exit_code() == 1


def test_49b_same_host_redirect_is_only_a_warning_when_allowed(monkeypatch):
    resp = FakeResponse(
        status_code=302,
        headers={"Location": "https://example.test/api/health/"},
        is_redirect=True,
    )
    monkeypatch.setattr(pdst.requests, "get", lambda *a, **k: resp)

    report = pdst.run("https://example.test/api", 5, 3000, allow_cross_host_redirect=False)

    by_name = {r.name: r for r in report.results}
    assert by_name["no_unexpected_redirect"].status == pdst.STATUS_WARNING
    assert by_name["no_unexpected_redirect"].required is False
    assert report.exit_code() == 0


# --------------------------------------------------------------------------
# 50: HTTP non-HTTPS ke host eksternal ditolak SEBELUM ada request dikirim
# --------------------------------------------------------------------------


def test_50_non_https_external_url_is_rejected():
    with pytest.raises(pdst.SmokeTestError):
        pdst.validate_base_url("http://example.com/api")


def test_50b_https_external_url_is_accepted():
    assert pdst.validate_base_url("https://example.com/api") == "https://example.com/api"


def test_50c_local_http_is_allowed():
    assert pdst.validate_base_url("http://localhost:5000/api") == "http://localhost:5000/api"


# --------------------------------------------------------------------------
# 51: kredensial ter-embed di URL (user:pass@host) ditolak
# --------------------------------------------------------------------------


def test_51_embedded_url_credentials_are_rejected():
    with pytest.raises(pdst.SmokeTestError):
        pdst.validate_base_url("https://user:pass@example.com/api")


# --------------------------------------------------------------------------
# 52: header X-Request-ID nggak ada di respons -> gagal (WAJIB)
# --------------------------------------------------------------------------


def test_52_missing_request_id_header_fails(monkeypatch):
    resp = FakeResponse(
        status_code=200,
        headers={"Content-Type": "application/json"},  # sengaja TANPA X-Request-ID
        json_data={"status": "ok", "database": "ok", "request_id": "abc"},
    )
    monkeypatch.setattr(pdst.requests, "get", lambda *a, **k: resp)

    report = pdst.run("https://example.test/api", 5, 3000, False)

    by_name = {r.name: r for r in report.results}
    assert by_name["request_id_header"].status == pdst.STATUS_FAILED
    assert report.exit_code() == 1


# --------------------------------------------------------------------------
# 53: status "degraded" di body -> gagal (deployment terdeteksi nggak sehat)
# --------------------------------------------------------------------------


def test_53_degraded_health_status_fails(monkeypatch):
    resp = FakeResponse(
        status_code=200,
        headers={"Content-Type": "application/json", "X-Request-ID": "abc"},
        json_data={"status": "degraded", "database": "unavailable", "request_id": "abc"},
    )
    monkeypatch.setattr(pdst.requests, "get", lambda *a, **k: resp)

    report = pdst.run("https://example.test/api", 5, 3000, False)

    by_name = {r.name: r for r in report.results}
    assert by_name["health_shape"].status == pdst.STATUS_FAILED
    assert report.exit_code() == 1


# --------------------------------------------------------------------------
# 54: script cuma PERNAH manggil GET /health — nggak pernah bikin/ubah data
# --------------------------------------------------------------------------


def test_54_only_calls_get_on_health_endpoint_never_mutates(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(
            status_code=200,
            headers={"Content-Type": "application/json", "X-Request-ID": "rid-1"},
            json_data={"status": "ok", "database": "ok", "request_id": "rid-1"},
        )

    def forbidden(method_name):
        def _raise(*args, **kwargs):
            raise AssertionError(f"post_deploy_smoke_test should never call requests.{method_name}()")
        return _raise

    monkeypatch.setattr(pdst.requests, "get", fake_get)
    for method_name in ("post", "put", "patch", "delete"):
        monkeypatch.setattr(pdst.requests, method_name, forbidden(method_name), raising=False)

    report = pdst.run("https://example.test/api", 5, 3000, False)

    assert calls == ["https://example.test/api/health"]
    assert report.exit_code() == 0


# --------------------------------------------------------------------------
# ekstra: nggak pernah ngirim header autentikasi apa pun
# --------------------------------------------------------------------------


def test_no_auth_headers_are_ever_sent(monkeypatch):
    captured_kwargs = {}

    def fake_get(url, **kwargs):
        captured_kwargs.update(kwargs)
        return FakeResponse(
            status_code=200,
            headers={"Content-Type": "application/json", "X-Request-ID": "rid-1"},
            json_data={"status": "ok", "database": "ok", "request_id": "rid-1"},
        )

    monkeypatch.setattr(pdst.requests, "get", fake_get)
    pdst.run("https://example.test/api", 5, 3000, False)

    assert "headers" not in captured_kwargs
    assert "auth" not in captured_kwargs
    assert "cookies" not in captured_kwargs
