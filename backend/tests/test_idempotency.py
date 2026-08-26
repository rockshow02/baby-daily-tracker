from models import IdempotencyKey
from tests.conftest import auth_headers, create_child, register


def _feeding_payload():
    return {"feed_type": "asi_langsung", "duration_minutes": 10}


def test_create_with_idempotency_key_succeeds(client):
    user = register(client)
    child = create_child(client, user["token"])

    resp = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json=_feeding_payload(),
        headers={**auth_headers(user["token"]), "X-Idempotency-Key": "key-1"},
    )
    assert resp.status_code == 201
    assert resp.get_json()["feed_type"] == "asi_langsung"


def test_repeated_key_returns_original_no_duplicate(client):
    user = register(client)
    child = create_child(client, user["token"])
    headers = {**auth_headers(user["token"]), "X-Idempotency-Key": "same-key"}

    first = client.post(
        f"/api/children/{child['id']}/feeding-logs", json=_feeding_payload(), headers=headers
    )
    second = client.post(
        f"/api/children/{child['id']}/feeding-logs", json=_feeding_payload(), headers=headers
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.get_json()["id"] == second.get_json()["id"]

    listed = client.get(
        f"/api/children/{child['id']}/feeding-logs?date={first.get_json()['timestamp'][:10]}",
        headers=auth_headers(user["token"]),
    )
    assert len(listed.get_json()) == 1


def test_different_key_creates_separate_record(client):
    user = register(client)
    child = create_child(client, user["token"])

    first = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json=_feeding_payload(),
        headers={**auth_headers(user["token"]), "X-Idempotency-Key": "key-a"},
    )
    second = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json=_feeding_payload(),
        headers={**auth_headers(user["token"]), "X-Idempotency-Key": "key-b"},
    )

    assert first.get_json()["id"] != second.get_json()["id"]


def test_missing_key_still_works_backward_compatible(client):
    user = register(client)
    child = create_child(client, user["token"])

    resp = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json=_feeding_payload(),
        headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 201


def test_same_key_different_endpoint_not_treated_as_collision(client, app):
    user = register(client)
    child = create_child(client, user["token"])
    headers = {**auth_headers(user["token"]), "X-Idempotency-Key": "shared-key"}

    feeding = client.post(
        f"/api/children/{child['id']}/feeding-logs", json=_feeding_payload(), headers=headers
    )
    sleep = client.post(
        f"/api/children/{child['id']}/sleep-logs",
        json={"start_time": "2024-01-01T10:00:00"},
        headers=headers,
    )

    assert feeding.status_code == 201
    assert sleep.status_code == 201
    assert IdempotencyKey.query.count() == 2


def test_same_key_different_child_not_treated_as_collision(client, app):
    user = register(client)
    child_a = create_child(client, user["token"], name="Baby A")
    child_b = create_child(client, user["token"], name="Baby B")
    headers = {**auth_headers(user["token"]), "X-Idempotency-Key": "shared-key"}

    resp_a = client.post(
        f"/api/children/{child_a['id']}/feeding-logs", json=_feeding_payload(), headers=headers
    )
    resp_b = client.post(
        f"/api/children/{child_b['id']}/feeding-logs", json=_feeding_payload(), headers=headers
    )

    assert resp_a.status_code == 201
    assert resp_b.status_code == 201
    assert resp_a.get_json()["id"] != resp_b.get_json()["id"]


def test_same_key_same_payload_returns_original_response(client):
    user = register(client)
    child = create_child(client, user["token"])
    headers = {**auth_headers(user["token"]), "X-Idempotency-Key": "fp-key"}

    first = client.post(
        f"/api/children/{child['id']}/feeding-logs", json=_feeding_payload(), headers=headers
    )
    second = client.post(
        f"/api/children/{child['id']}/feeding-logs", json=_feeding_payload(), headers=headers
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.get_json() == second.get_json()
    assert IdempotencyKey.query.count() == 1


def test_same_key_different_payload_returns_409_conflict(client):
    user = register(client)
    child = create_child(client, user["token"])
    headers = {**auth_headers(user["token"]), "X-Idempotency-Key": "fp-key-conflict"}

    first = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json={"feed_type": "asi_langsung", "duration_minutes": 10},
        headers=headers,
    )
    second = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json={"feed_type": "sufor", "volume_ml": 90},  # payload BEDA, key SAMA
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert "error" in second.get_json()

    from models import FeedingLog

    logs = FeedingLog.query.all()
    assert len(logs) == 1  # request kedua NGGAK bikin log baru
    # yang KESIMPEN itu data yang PERTAMA (yang beneran sukses), bukan
    # data konflik yang ditolak — catatan asli tetap utuh buat ditinjau
    assert logs[0].feed_type == "asi_langsung"
    assert logs[0].volume_ml is None

    # request KETIGA dengan key yang sama dan payload yang SAMA PERSIS
    # kayak yang pertama (bukan yang konflik) harus tetep balikin record
    # asli itu — 409 di atas TIDAK ngerusak/nge-invalidate baris
    # idempotency yang udah sah kesimpen duluan
    third = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json={"feed_type": "asi_langsung", "duration_minutes": 10},
        headers=headers,
    )
    assert third.status_code == 201
    assert third.get_json()["id"] == first.get_json()["id"]
    assert FeedingLog.query.count() == 1


def test_medication_log_idempotency(client):
    user = register(client)
    child = create_child(client, user["token"])
    headers = {**auth_headers(user["token"]), "X-Idempotency-Key": "med-key"}
    payload = {"medication_name": "Paracetamol", "dosage": "1 ml"}

    first = client.post(
        f"/api/children/{child['id']}/medication-logs", json=payload, headers=headers
    )
    second = client.post(
        f"/api/children/{child['id']}/medication-logs", json=payload, headers=headers
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.get_json()["id"] == second.get_json()["id"]
