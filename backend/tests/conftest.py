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


@pytest.fixture
def app():
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
