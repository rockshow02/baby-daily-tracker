"""
Test konkurensi beneran (thread asli, bukan simulasi berurutan) buat
mastiin idempotent_create() aman kalau 2 request sama persis nyampe
HAMPIR BERBARENGAN — skenario yang paling mungkin kejadian pas HP balik
online dan ngirim ulang antrian, sementara request pertamanya sebenernya
udah nyampe server tapi klien mikir belum.

SENGAJA pakai SQLite FILE sementara + NullPool (bukan ":memory:" kayak
fixture `app`/`client` biasa) — ":memory:" SQLite bikin database TERPISAH
per koneksi (atau, kalau Flask-SQLAlchemy otomatis maksa StaticPool buat
":memory:", malah bikin 2 thread beneran gantian pakai SATU objek koneksi
yang sama secara bersamaan — bikin driver sqlite3 korup, bukan nyimulasiin
race condition yang bener). File sementara + NullPool = tiap thread beneran
dapet koneksi sendiri ke database FILE yang sama, jadi unique constraint-nya
beneran diuji lewat kunci file SQLite yang sebenarnya. File dihapus otomatis
di akhir test, nggak pernah nyentuh instance/tracker.db yang beneran dipakai
app.
"""
import os
import tempfile
import threading

import pytest
from sqlalchemy.pool import NullPool

from app import create_app
from extensions import db
from tests.conftest import auth_headers, create_child, register


@pytest.fixture
def file_db_app():
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    application = create_app(
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path}",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "poolclass": NullPool,
                "connect_args": {"check_same_thread": False},
            },
        }
    )
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()
    os.remove(path)


def test_concurrent_same_key_creates_exactly_one_log_and_one_notification(file_db_app, monkeypatch):
    calls = []
    monkeypatch.setattr("routes.daily_log_routes.notify_other_caregivers", lambda *a, **k: calls.append(1))

    client = file_db_app.test_client()
    user = register(client)
    child = create_child(client, user["token"])
    headers = {**auth_headers(user["token"]), "X-Idempotency-Key": "race-key"}
    payload = {"feed_type": "asi_langsung", "duration_minutes": 5}

    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        with file_db_app.test_client() as c:
            resp = c.post(f"/api/children/{child['id']}/feeding-logs", json=payload, headers=headers)
            results.append(resp.status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [201, 201]  # kedua request "sukses" dari sudut pandang klien...

    from models import FeedingLog, IdempotencyKey

    assert FeedingLog.query.count() == 1  # ...tapi cuma 1 log yang beneran kesimpen
    assert IdempotencyKey.query.count() == 1
    assert len(calls) == 1  # dan cuma 1 notifikasi yang terkirim
