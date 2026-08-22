import os
import sys

# backend/ (bukan backend/tests/) harus ada di sys.path, soalnya seluruh
# kode app (app.py, models.py, routes/, utils/) saling import tanpa
# prefix paket (mis. `from extensions import db`), bukan import relatif.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# WAJIB di-set sebelum create_app() dipanggil di fixture manapun — testing
# config pakai SQLite in-memory, jadi tes nggak akan PERNAH nyentuh
# instance/tracker.db yang beneran dipakai di dev/production.
os.environ["FLASK_ENV"] = "testing"

import pytest

from app import create_app
from extensions import db

# Origin frontend yang DETERMINISTIK buat seluruh test suite — app.py baca
# FRONTEND_ORIGIN dari os.environ tiap create_app() dipanggil (biar production
# gampang dikonfigurasi ulang tanpa redeploy kode), tapi itu artinya test yang
# ngirim header `Origin: http://localhost:5173` bisa gagal di mesin mana pun
# yang kebetulan udah punya FRONTEND_ORIGIN lain ke-set (mis. PythonAnywhere,
# yang env host-nya nunjuk ke origin Vercel staging beneran, bukan localhost).
# lihat fixture frontend_origin_env di bawah — dipaksa SEBELUM app dibikin,
# jadi test CORS nggak pernah bergantung sama apa pun yang ada di environment
# host.
TEST_FRONTEND_ORIGIN = "http://localhost:5173"


@pytest.fixture
def frontend_origin_env(monkeypatch):
    """
    Paksa FRONTEND_ORIGIN ke nilai test yang deterministik SEBELUM
    create_app() dipanggil — apa pun yang kebetulan udah ke-set di
    environment host (FRONTEND_ORIGIN, FRONTEND_URL, atau sejenisnya).
    `monkeypatch` otomatis balikin env var ini ke nilai semula (atau
    unset) begitu test ini kelar, jadi nggak ada state yang bocor ke test
    lain — dipusatkan di sini biar test CORS individual nggak perlu
    ngulang-ngulang manipulasi environment sendiri-sendiri.
    """
    monkeypatch.setenv("FRONTEND_ORIGIN", TEST_FRONTEND_ORIGIN)
    return TEST_FRONTEND_ORIGIN


@pytest.fixture
def app(frontend_origin_env):
    application = create_app()
    with application.app_context():
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, name="Test User", email="test@example.com", password="password123"):
    resp = client.post(
        "/api/auth/register", json={"name": name, "email": email, "password": password}
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def create_child(client, token, name="Baby Test"):
    from datetime import timedelta

    from utils.timezone_utils import today_wib

    birth_date = (today_wib() - timedelta(days=60)).isoformat()
    resp = client.post(
        "/api/children",
        json={"name": name, "birth_date": birth_date, "gender": "L"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()
