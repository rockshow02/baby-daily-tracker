"""
Test GET /api/children/<id>/audit-events — otorisasi, paginasi, filter,
dan privasi respons. Lihat tests/test_audit_trail.py buat test
create/update/delete audit event-nya sendiri.
"""
from datetime import datetime

import pytest

from extensions import db
from models import CaregiverAuditEvent
from tests.conftest import auth_headers, create_child, register
from tests.test_audit_trail import add_caregiver, ENTITY_SPECS


def _create_feeding(client, token, child_id, idem_key):
    resp = client.post(
        f"/api/children/{child_id}/feeding-logs",
        json=ENTITY_SPECS["feeding_log"]["create_payload"],
        headers={**auth_headers(token), "X-Idempotency-Key": idem_key},
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _list(client, token, child_id, **params):
    return client.get(f"/api/children/{child_id}/audit-events", query_string=params, headers=auth_headers(token))


# --------------------------------------------------------------------------
# Otorisasi
# --------------------------------------------------------------------------


def test_1_owner_can_read_events(client):
    user = register(client)
    child = create_child(client, user["token"])
    _create_feeding(client, user["token"], child["id"], "k1")

    resp = _list(client, user["token"], child["id"])
    assert resp.status_code == 200
    assert len(resp.get_json()["events"]) == 1


def test_2_caregiver_can_read_events(client):
    owner = register(client, name="Owner", email="owner@example.com")
    child = create_child(client, owner["token"])
    caregiver = register(client, name="Caregiver", email="caregiver@example.com")
    add_caregiver(client, owner["token"], child["id"], caregiver["token"])
    _create_feeding(client, owner["token"], child["id"], "k1")

    resp = _list(client, caregiver["token"], child["id"])
    assert resp.status_code == 200
    assert len(resp.get_json()["events"]) == 1


def test_3_removed_caregiver_cannot_read_events_after_access_removal(client):
    owner = register(client, name="Owner", email="owner@example.com")
    child = create_child(client, owner["token"])
    caregiver = register(client, name="Caregiver", email="caregiver@example.com")
    add_caregiver(client, owner["token"], child["id"], caregiver["token"])
    _create_feeding(client, owner["token"], child["id"], "k1")

    assert _list(client, caregiver["token"], child["id"]).status_code == 200

    remove_resp = client.delete(
        f"/api/children/{child['id']}/caregivers/{caregiver['id']}", headers=auth_headers(owner["token"])
    )
    assert remove_resp.status_code == 200

    resp = _list(client, caregiver["token"], child["id"])
    assert resp.status_code == 404  # sama kayak pola akses lain di app ini


def test_4_unrelated_authenticated_user_gets_safe_not_found(client):
    owner = register(client, name="Owner", email="owner@example.com")
    child = create_child(client, owner["token"])
    _create_feeding(client, owner["token"], child["id"], "k1")

    stranger = register(client, name="Stranger", email="stranger@example.com")
    resp = _list(client, stranger["token"], child["id"])
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "Anak tidak ditemukan"}  # sama persis pesan generik endpoint lain


def test_5_unauthenticated_request_is_rejected(app, client):
    owner = register(client, name="Owner", email="owner@example.com")
    child = create_child(client, owner["token"])

    # `client` udah "kebawa login" lewat session cookie yang register()
    # tinggalin (fallback selain Bearer token — lihat utils/auth.py) —
    # test "beneran nggak login" butuh client BARU yang belum pernah
    # nyimpen cookie apa pun, bukan cuma nggak ngirim header Authorization.
    anonymous_client = app.test_client()
    resp = anonymous_client.get(f"/api/children/{child['id']}/audit-events")
    assert resp.status_code == 401


def test_6_cannot_request_events_for_a_child_the_user_has_no_access_to(client):
    owner = register(client, name="Owner", email="owner@example.com")
    other_owner = register(client, name="OtherOwner", email="other@example.com")
    child_a = create_child(client, owner["token"])
    child_b = create_child(client, other_owner["token"])
    _create_feeding(client, owner["token"], child_a["id"], "k1")
    _create_feeding(client, other_owner["token"], child_b["id"], "k2")

    # owner nyoba baca audit event anak ORANG LAIN
    resp = _list(client, owner["token"], child_b["id"])
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "Anak tidak ditemukan"}


def test_401_before_404_does_not_leak_child_existence(app, client):
    """Unauthenticated request ke child_id yang BENERAN ada TETAP 401, bukan bocorin lewat beda status."""
    owner = register(client, name="Owner", email="owner@example.com")
    child = create_child(client, owner["token"])

    anonymous_client = app.test_client()
    resp = anonymous_client.get(f"/api/children/{child['id']}/audit-events")
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# Validasi filter/cursor/limit
# --------------------------------------------------------------------------


def test_7_invalid_action_filter_is_rejected_with_400(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = _list(client, owner["token"], child["id"], action="not-a-real-action")
    assert resp.status_code == 400


def test_7b_invalid_entity_type_filter_is_rejected_with_400(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = _list(client, owner["token"], child["id"], entity_type="not-a-real-type")
    assert resp.status_code == 400


def test_7c_invalid_actor_user_id_filter_is_rejected_with_400(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = _list(client, owner["token"], child["id"], actor_user_id="not-a-number")
    assert resp.status_code == 400


def test_7d_negative_actor_user_id_is_rejected_with_400(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = _list(client, owner["token"], child["id"], actor_user_id="-5")
    assert resp.status_code == 400


def test_7e_invalid_cursor_is_rejected_with_400(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = _list(client, owner["token"], child["id"], cursor="not-a-number")
    assert resp.status_code == 400


def test_7f_negative_cursor_is_rejected_with_400(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = _list(client, owner["token"], child["id"], cursor="-1")
    assert resp.status_code == 400


def test_7g_non_numeric_limit_is_rejected_with_400(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = _list(client, owner["token"], child["id"], limit="abc")
    assert resp.status_code == 400


def test_8_limit_above_maximum_is_rejected_with_400(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = _list(client, owner["token"], child["id"], limit="101")
    assert resp.status_code == 400


def test_8b_limit_of_exactly_100_is_allowed(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = _list(client, owner["token"], child["id"], limit="100")
    assert resp.status_code == 200


def test_8c_limit_of_zero_is_rejected_with_400(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = _list(client, owner["token"], child["id"], limit="0")
    assert resp.status_code == 400


def test_default_limit_is_25(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    for i in range(30):
        _create_feeding(client, owner["token"], child["id"], f"k{i}")

    resp = _list(client, owner["token"], child["id"])
    body = resp.get_json()
    assert len(body["events"]) == 25
    assert body["next_cursor"] is not None


def test_valid_filters_narrow_results_correctly(client):
    owner = register(client, name="Owner", email="owner@example.com")
    child = create_child(client, owner["token"])
    caregiver = register(client, name="Caregiver", email="caregiver@example.com")
    add_caregiver(client, owner["token"], child["id"], caregiver["token"])

    f1 = _create_feeding(client, owner["token"], child["id"], "k1")
    client.put(f"/api/feeding-logs/{f1['id']}", json={"duration_minutes": 99}, headers=auth_headers(caregiver["token"]))

    by_action = _list(client, owner["token"], child["id"], action="update").get_json()["events"]
    assert len(by_action) == 1
    assert by_action[0]["action"] == "update"

    by_entity = _list(client, owner["token"], child["id"], entity_type="feeding_log").get_json()["events"]
    assert len(by_entity) == 2  # create + update

    by_actor = _list(client, owner["token"], child["id"], actor_user_id=str(caregiver["id"])).get_json()["events"]
    assert len(by_actor) == 1
    assert by_actor[0]["actor_user_id"] == caregiver["id"]


# --------------------------------------------------------------------------
# Privasi respons
# --------------------------------------------------------------------------


def test_9_response_never_contains_sensitive_fields(client):
    owner = register(client, name="Owner", email="owner-secret@example.com")
    child = create_child(client, owner["token"])
    created = client.post(
        f"/api/children/{child['id']}/illness-logs",
        json={
            "illness_name": "RAHASIA MEDIS super sensitif",
            "start_date": "2026-01-10",
            "symptoms": "gejala rahasia banget",
            "notes": "catatan bebas rahasia",
        },
        headers=auth_headers(owner["token"]),
    ).get_json()
    client.put(
        f"/api/illness-logs/{created['id']}",
        json={"illness_name": "RAHASIA MEDIS BARU"},
        headers=auth_headers(owner["token"]),
    )
    client.delete(f"/api/illness-logs/{created['id']}", headers=auth_headers(owner["token"]))

    resp = _list(client, owner["token"], child["id"])
    raw = resp.get_data(as_text=True)

    forbidden = [
        "owner-secret@example.com", "RAHASIA MEDIS", "gejala rahasia", "catatan bebas rahasia",
        owner["token"], "Authorization", "X-Idempotency-Key", "request_id", "Traceback",
        "child_id",  # redundan — udah di URL, nggak perlu diulang tiap event
    ]
    for term in forbidden:
        assert term not in raw, f"respons audit-events mengandung {term!r}"

    # sanity: event-nya BENERAN ada (bukan cuma kebetulan list kosong)
    assert len(resp.get_json()["events"]) == 3


def test_9b_response_shape_only_contains_the_documented_safe_fields(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    _create_feeding(client, owner["token"], child["id"], "k1")

    events = _list(client, owner["token"], child["id"]).get_json()["events"]
    assert len(events) == 1
    assert set(events[0].keys()) == {
        "id", "action", "entity_type", "entity_id", "changed_fields",
        "recorded_at", "created_at", "actor_user_id", "actor_name",
    }


# --------------------------------------------------------------------------
# Endpoint public CUMA baca — nggak ada jalur create/update/delete manual
# --------------------------------------------------------------------------


def test_10_no_public_endpoint_can_create_edit_or_delete_audit_events(client):
    owner = register(client)
    child = create_child(client, owner["token"])

    for method in ("post", "put", "delete", "patch"):
        resp = getattr(client, method)(
            f"/api/children/{child['id']}/audit-events",
            json={"action": "create", "entity_type": "feeding_log", "entity_id": 1},
            headers=auth_headers(owner["token"]),
        )
        assert resp.status_code == 405, f"{method.upper()} harusnya nggak diizinkan di endpoint ini"

    assert CaregiverAuditEvent.query.count() == 0


# --------------------------------------------------------------------------
# Ordering & paginasi
# --------------------------------------------------------------------------


def test_ordering_is_stable_when_created_at_timestamps_match(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    _create_feeding(client, owner["token"], child["id"], "k1")
    resp2 = client.post(
        f"/api/children/{child['id']}/sleep-logs",
        json=ENTITY_SPECS["sleep_log"]["create_payload"],
        headers={**auth_headers(owner["token"]), "X-Idempotency-Key": "k2"},
    )
    assert resp2.status_code == 201

    # paksa created_at SAMA PERSIS buat kedua event — bukti urutannya
    # nggak bisa "goyah" cuma gara-gara timestamp identik
    same_ts = datetime(2026, 1, 1, 12, 0, 0)
    for ev in CaregiverAuditEvent.query.filter_by(child_id=child["id"]).all():
        ev.created_at = same_ts
    db.session.commit()

    first = _list(client, owner["token"], child["id"]).get_json()["events"]
    second = _list(client, owner["token"], child["id"]).get_json()["events"]
    assert [e["id"] for e in first] == [e["id"] for e in second]
    ids = [e["id"] for e in first]
    assert ids == sorted(ids, reverse=True)


def test_pagination_does_not_duplicate_or_skip_events(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    for i in range(7):
        _create_feeding(client, owner["token"], child["id"], f"k{i}")

    all_events = _list(client, owner["token"], child["id"], limit=100).get_json()["events"]
    assert len(all_events) == 7

    collected = []
    cursor = None
    for _ in range(20):  # batas iterasi jaga-jaga biar test nggak infinite loop kalau ada bug
        params = {"limit": 3}
        if cursor is not None:
            params["cursor"] = cursor
        page = _list(client, owner["token"], child["id"], **params).get_json()
        collected.extend(page["events"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert [e["id"] for e in collected] == [e["id"] for e in all_events]
    assert len(collected) == len(set(e["id"] for e in collected))  # nggak ada duplikat
