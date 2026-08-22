from sqlalchemy.orm import Session

from tests.conftest import auth_headers, create_child, register


def _feeding_payload():
    return {"feed_type": "asi_langsung", "duration_minutes": 10}


def test_replay_sends_only_one_notification(client, monkeypatch):
    user = register(client)
    child = create_child(client, user["token"])
    calls = []
    monkeypatch.setattr("routes.daily_log_routes.notify_other_caregivers", lambda *a, **k: calls.append(1))
    headers = {**auth_headers(user["token"]), "X-Idempotency-Key": "notify-key"}

    first = client.post(f"/api/children/{child['id']}/feeding-logs", json=_feeding_payload(), headers=headers)
    second = client.post(f"/api/children/{child['id']}/feeding-logs", json=_feeding_payload(), headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert len(calls) == 1  # replay TIDAK memicu notifikasi lagi


def test_conflicting_replay_sends_no_notification(client, monkeypatch):
    user = register(client)
    child = create_child(client, user["token"])
    calls = []
    monkeypatch.setattr("routes.daily_log_routes.notify_other_caregivers", lambda *a, **k: calls.append(1))
    headers = {**auth_headers(user["token"]), "X-Idempotency-Key": "notify-conflict-key"}

    client.post(f"/api/children/{child['id']}/feeding-logs", json=_feeding_payload(), headers=headers)
    conflict = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json={"feed_type": "sufor", "volume_ml": 90},
        headers=headers,
    )

    assert conflict.status_code == 409
    assert len(calls) == 1  # cuma request pertama (yang beneran kesimpen) yang notify


def test_failed_commit_sends_no_notification(client, monkeypatch):
    user = register(client)
    child = create_child(client, user["token"])
    calls = []
    monkeypatch.setattr("routes.daily_log_routes.notify_other_caregivers", lambda *a, **k: calls.append(1))

    def raise_commit(self, *a, **k):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(Session, "commit", raise_commit)

    # PROPAGATE_EXCEPTIONS=False (lihat app.py) — exception nggak lagi
    # nembus ke pemanggil test_client(), tapi ketangkep global error
    # handler dan jadi respons 500 yang aman (lihat utils/observability.py
    # dan tests/test_observability.py buat kontrak lengkapnya). Invariant
    # yang beneran mau diuji di sini TETAP SAMA: commit gagal -> notifikasi
    # TIDAK terkirim.
    resp = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json=_feeding_payload(),
        headers={**auth_headers(user["token"]), "X-Idempotency-Key": "fail-commit-key"},
    )

    assert resp.status_code == 500
    assert calls == []


def test_notification_failure_does_not_fail_the_saved_log(client, monkeypatch):
    user = register(client)
    child = create_child(client, user["token"])

    def raise_notify(*a, **k):
        raise RuntimeError("telegram down")

    monkeypatch.setattr("routes.daily_log_routes.notify_other_caregivers", raise_notify)

    resp = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json=_feeding_payload(),
        headers={**auth_headers(user["token"]), "X-Idempotency-Key": "notify-fail-key"},
    )

    assert resp.status_code == 201

    from models import FeedingLog

    assert FeedingLog.query.count() == 1
