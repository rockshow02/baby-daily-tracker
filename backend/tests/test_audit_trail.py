"""
Test Caregiver Audit Trail (Phase 1) — utils/audit.py, model
CaregiverAuditEvent, dan endpoint GET /api/children/<id>/audit-events.

SEMUA test pakai fixture `client`/`file_db_app` (SQLite in-memory atau
file sementara), TIDAK PERNAH menyentuh instance/tracker.db asli.
"""
import os
import tempfile
import threading
from datetime import datetime

import pytest
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app import create_app
from extensions import db
from models import CaregiverAuditEvent, FeedingLog
from tests.conftest import auth_headers, create_child, register

# --------------------------------------------------------------------------
# Spesifikasi per entity_type — cukup buat nge-drive test create/update/
# delete generik lewat 1 body test, bukan nulis 12x kode yang sama persis.
# --------------------------------------------------------------------------

ENTITY_SPECS = {
    "feeding_log": {
        "create_path": "feeding-logs",
        "item_path": "feeding-logs",
        "create_payload": {"feed_type": "asi_langsung", "duration_minutes": 5},
        "meaningful_update": {"duration_minutes": 15},
        "noop_update": {"duration_minutes": 5},
        "idempotent": True,
    },
    "sleep_log": {
        "create_path": "sleep-logs",
        "item_path": "sleep-logs",
        "create_payload": {"start_time": "2026-01-10T20:00:00", "sleep_type": "siang"},
        "meaningful_update": {"sleep_type": "malam"},
        "noop_update": {"sleep_type": "siang"},
        "idempotent": True,
    },
    "diaper_log": {
        "create_path": "diaper-logs",
        "item_path": "diaper-logs",
        "create_payload": {"diaper_type": "pipis"},
        "meaningful_update": {"diaper_type": "pup"},
        "noop_update": {"diaper_type": "pipis"},
        "idempotent": True,
    },
    "pumping_log": {
        "create_path": "pumping-logs",
        "item_path": "pumping-logs",
        "create_payload": {"duration_minutes": 10, "volume_ml": 50},
        "meaningful_update": {"volume_ml": 80},
        "noop_update": {"volume_ml": 50},
        "idempotent": True,
    },
    "activity_log": {
        "create_path": "activity-logs",
        "item_path": "activity-logs",
        "create_payload": {"activity_type": "stroll", "duration_minutes": 20},
        "meaningful_update": {"duration_minutes": 30},
        "noop_update": {"duration_minutes": 20},
        "idempotent": True,
    },
    "growth_measurement": {
        "create_path": "growth-measurements",
        "item_path": "growth-measurements",
        "create_payload": {"measured_date": "2026-01-10", "weight_kg": 5.0},
        "meaningful_update": {"weight_kg": 5.5},
        "noop_update": {"weight_kg": 5.0},
        "idempotent": False,
    },
    "doctor_visit": {
        "create_path": "doctor-visits",
        "item_path": "doctor-visits",
        "create_payload": {"visit_date": "2026-01-10", "doctor_name": "Dr. A"},
        "meaningful_update": {"doctor_name": "Dr. B"},
        "noop_update": {"doctor_name": "Dr. A"},
        "idempotent": False,
    },
    "temperature_log": {
        "create_path": "temperature-logs",
        "item_path": "temperature-logs",
        "create_payload": {"temperature_celsius": 37.0},
        "meaningful_update": {"temperature_celsius": 38.5},
        "noop_update": {"temperature_celsius": 37.0},
        "idempotent": False,
    },
    "illness_log": {
        "create_path": "illness-logs",
        "item_path": "illness-logs",
        "create_payload": {"illness_name": "Flu", "start_date": "2026-01-10"},
        "meaningful_update": {"illness_name": "Batuk"},
        "noop_update": {"illness_name": "Flu"},
        "idempotent": False,
    },
    "medication_log": {
        "create_path": "medication-logs",
        "item_path": "medication-logs",
        "create_payload": {"medication_name": "Paracetamol", "dosage": "5ml"},
        "meaningful_update": {"dosage": "10ml"},
        "noop_update": {"dosage": "5ml"},
        "idempotent": True,
    },
    "mood_log": {
        "create_path": "mood-logs",
        "item_path": "mood-logs",
        "create_payload": {"mood": "ceria"},
        "meaningful_update": {"mood": "sedih"},
        "noop_update": {"mood": "ceria"},
        "idempotent": False,
    },
    "milestone_log": {
        "create_path": "milestone-logs",
        "item_path": "milestone-logs",
        "create_payload": {"milestone_type": "bisa_duduk", "achieved_date": "2026-01-10"},
        "meaningful_update": {"achieved_date": "2026-01-11"},
        "noop_update": {"achieved_date": "2026-01-10"},
        "idempotent": False,
    },
}

ENTITY_TYPES = list(ENTITY_SPECS.keys())


def _create(client, token, child_id, entity_type, idem_key=None, payload=None):
    spec = ENTITY_SPECS[entity_type]
    headers = auth_headers(token)
    if spec["idempotent"]:
        headers = {**headers, "X-Idempotency-Key": idem_key or f"{entity_type}-default-key"}
    resp = client.post(
        f"/api/children/{child_id}/{spec['create_path']}",
        json=payload or spec["create_payload"],
        headers=headers,
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _update(client, token, entity_type, entity_id, payload):
    spec = ENTITY_SPECS[entity_type]
    resp = client.put(f"/api/{spec['item_path']}/{entity_id}", json=payload, headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _delete(client, token, entity_type, entity_id):
    spec = ENTITY_SPECS[entity_type]
    resp = client.delete(f"/api/{spec['item_path']}/{entity_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_json()


def _list_events(client, token, child_id, **params):
    return client.get(f"/api/children/{child_id}/audit-events", query_string=params, headers=auth_headers(token))


def add_caregiver(client, owner_token, child_id, caregiver_token):
    invite = client.post(f"/api/children/{child_id}/invite", headers=auth_headers(owner_token))
    assert invite.status_code == 201, invite.get_json()
    code = invite.get_json()["code"]
    join = client.post("/api/children/join", json={"code": code}, headers=auth_headers(caregiver_token))
    assert join.status_code == 201, join.get_json()


# --------------------------------------------------------------------------
# Functional: create / update / delete, per entity_type
# --------------------------------------------------------------------------


@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
def test_create_records_exactly_one_create_event(client, entity_type):
    user = register(client)
    child = create_child(client, user["token"])
    created = _create(client, user["token"], child["id"], entity_type, idem_key="create-key")

    events = _list_events(client, user["token"], child["id"]).get_json()["events"]
    assert len(events) == 1
    ev = events[0]
    assert ev["action"] == "create"
    assert ev["entity_type"] == entity_type
    assert ev["entity_id"] == created["id"]
    assert ev["changed_fields"] == []
    assert ev["actor_user_id"] == user["id"]
    assert ev["actor_name"] == user["name"]


@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
def test_meaningful_update_records_an_update_event_with_only_the_changed_field_names(client, entity_type):
    spec = ENTITY_SPECS[entity_type]
    user = register(client)
    child = create_child(client, user["token"])
    created = _create(client, user["token"], child["id"], entity_type, idem_key="create-key")
    _update(client, user["token"], entity_type, created["id"], spec["meaningful_update"])

    events = _list_events(client, user["token"], child["id"]).get_json()["events"]
    update_events = [e for e in events if e["action"] == "update"]
    assert len(update_events) == 1
    assert set(update_events[0]["changed_fields"]) == set(spec["meaningful_update"].keys())
    assert update_events[0]["entity_id"] == created["id"]


@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
def test_noop_update_does_not_create_an_audit_event(client, entity_type):
    spec = ENTITY_SPECS[entity_type]
    user = register(client)
    child = create_child(client, user["token"])
    created = _create(client, user["token"], child["id"], entity_type, idem_key="create-key")
    _update(client, user["token"], entity_type, created["id"], spec["noop_update"])

    events = _list_events(client, user["token"], child["id"]).get_json()["events"]
    assert [e["action"] for e in events] == ["create"]  # nggak nambah baris "update"


@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
def test_delete_records_a_delete_event_with_original_entity_id(client, entity_type):
    user = register(client)
    child = create_child(client, user["token"])
    created = _create(client, user["token"], child["id"], entity_type, idem_key="create-key")
    _delete(client, user["token"], entity_type, created["id"])

    events = _list_events(client, user["token"], child["id"]).get_json()["events"]
    delete_events = [e for e in events if e["action"] == "delete"]
    assert len(delete_events) == 1
    assert delete_events[0]["entity_id"] == created["id"]
    assert delete_events[0]["actor_user_id"] == user["id"]


# --------------------------------------------------------------------------
# Actor correctness / creator attribution
# --------------------------------------------------------------------------


def test_actor_is_the_user_performing_the_update_not_the_original_creator(client):
    owner = register(client, name="Pemilik", email="owner@example.com")
    child = create_child(client, owner["token"])
    caregiver = register(client, name="Pengasuh", email="caregiver@example.com")
    add_caregiver(client, owner["token"], child["id"], caregiver["token"])

    created = _create(client, owner["token"], child["id"], "feeding_log", idem_key="k1")
    _update(client, caregiver["token"], "feeding_log", created["id"], {"duration_minutes": 99})

    events = _list_events(client, owner["token"], child["id"]).get_json()["events"]
    update_ev = next(e for e in events if e["action"] == "update")
    assert update_ev["actor_user_id"] == caregiver["id"]
    assert update_ev["actor_name"] == "Pengasuh"

    create_ev = next(e for e in events if e["action"] == "create")
    assert create_ev["actor_user_id"] == owner["id"]

    # atribusi PEMBUAT record itu sendiri (fitur lama, terpisah dari audit
    # trail) TETAP nunjuk ke owner — nggak ikut "pindah" ke caregiver yang
    # ngedit belakangan
    logs = client.get(
        f"/api/children/{child['id']}/feeding-logs", headers=auth_headers(owner["token"])
    ).get_json()
    log = next(l for l in logs if l["id"] == created["id"])
    assert log["created_by_name"] == "Pemilik"


def test_deleted_entity_leaves_a_minimal_audit_event_without_medical_values(client):
    user = register(client)
    child = create_child(client, user["token"])
    created = _create(
        client, user["token"], child["id"], "illness_log",
        payload={"illness_name": "RAHASIA MEDIS", "start_date": "2026-01-10", "symptoms": "gejala rahasia"},
    )
    _delete(client, user["token"], "illness_log", created["id"])

    events = _list_events(client, user["token"], child["id"]).get_json()["events"]
    delete_ev = next(e for e in events if e["action"] == "delete")
    payload_text = str(delete_ev)
    assert "RAHASIA MEDIS" not in payload_text
    assert "gejala rahasia" not in payload_text
    assert set(delete_ev.keys()) == {
        "id", "action", "entity_type", "entity_id", "changed_fields",
        "recorded_at", "created_at", "actor_user_id", "actor_name",
    }


# --------------------------------------------------------------------------
# Idempotent replay & concurrency
# --------------------------------------------------------------------------


def test_idempotent_replay_does_not_create_a_second_audit_event(client):
    user = register(client)
    child = create_child(client, user["token"])
    headers = {**auth_headers(user["token"]), "X-Idempotency-Key": "replay-key"}
    payload = {"feed_type": "asi_langsung", "duration_minutes": 5}

    r1 = client.post(f"/api/children/{child['id']}/feeding-logs", json=payload, headers=headers)
    assert r1.status_code == 201
    r2 = client.post(f"/api/children/{child['id']}/feeding-logs", json=payload, headers=headers)
    assert r2.status_code == 201
    assert r1.get_json()["id"] == r2.get_json()["id"]  # record yang SAMA, bukan baru

    events = _list_events(client, user["token"], child["id"]).get_json()["events"]
    assert len([e for e in events if e["action"] == "create"]) == 1


def test_commit_failure_rolls_back_both_the_entity_and_its_audit_event(client, monkeypatch):
    user = register(client)
    child = create_child(client, user["token"])

    def raise_commit(self, *a, **k):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(Session, "commit", raise_commit)

    resp = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json={"feed_type": "asi_langsung"},
        headers={**auth_headers(user["token"]), "X-Idempotency-Key": "fail-commit-key"},
    )
    assert resp.status_code == 500
    # `client` fixture (tests/conftest.py) udah nge-push 1 app context
    # MANUAL yang tetep aktif sepanjang test ini — Flask test client
    # nggak pernah nge-pop/dorong context BARU di atasnya kalau satu
    # udah aktif, jadi `teardown_appcontext` (yang biasanya motor
    # db.session.remove()/rollback abis 1 request BENERAN kelar) BELUM
    # sempat kepanggil sampai fixture-nya sendiri keluar dari blok
    # `with`-nya di akhir test. Query langsung lewat db.session yang SAMA
    # (belum di-rollback) bakal masih "keliatan" ngelihat baris yang udah
    # di-flush tapi gagal commit — itu bukan berarti rollback-nya nggak
    # jalan, cuma REPRESENTASI STATE SEBELUM cleanup normal kejadian.
    # rollback() manual di sini nyimulasiin PERSIS itu, biar assert-nya
    # ngecek state SESUDAH transaksi beneran dianggap batal (yang bakal
    # kejadian otomatis di request BERIKUTNYA lewat teardown Flask asli).
    db.session.rollback()
    assert FeedingLog.query.count() == 0
    assert CaregiverAuditEvent.query.count() == 0


@pytest.fixture
def file_db_app():
    """SQLite file sementara + NullPool — buat test konkurensi thread ASLI (lihat tests/test_concurrency.py)."""
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


def test_concurrent_idempotent_create_produces_exactly_one_entity_and_one_audit_event(file_db_app):
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

    assert sorted(results) == [201, 201]
    with file_db_app.app_context():
        assert FeedingLog.query.count() == 1
        assert CaregiverAuditEvent.query.filter_by(action="create").count() == 1


# --------------------------------------------------------------------------
# Child deletion cascade / legacy records
# --------------------------------------------------------------------------


def test_deleting_a_child_cascades_deletes_its_audit_events(client):
    user = register(client)
    child = create_child(client, user["token"])
    _create(client, user["token"], child["id"], "feeding_log", idem_key="k1")

    assert CaregiverAuditEvent.query.filter_by(child_id=child["id"]).count() == 1

    resp = client.delete(f"/api/children/{child['id']}", headers=auth_headers(user["token"]))
    assert resp.status_code == 200
    assert CaregiverAuditEvent.query.filter_by(child_id=child["id"]).count() == 0


def test_legacy_pre_feature_records_do_not_receive_fabricated_events(client):
    """
    Record yang "udah ada" SEBELUM fitur ini (disimulasikan lewat insert
    langsung, BYPASS route/helper audit) TIDAK PERNAH otomatis dapet
    audit event cuma karena kebaca/ke-list — nggak ada backfill historis.
    """
    user = register(client)
    child = create_child(client, user["token"])

    legacy_log = FeedingLog(child_id=child["id"], feed_type="asi_langsung", created_by_user_id=user["id"])
    db.session.add(legacy_log)
    db.session.commit()

    events = _list_events(client, user["token"], child["id"]).get_json()["events"]
    assert events == []
