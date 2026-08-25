"""
Test Caregiver Handover Summary — Phase 1
(`/children/<id>/caregiver-handover`, `/caregiver-handovers/<id>` dkk).
Lihat backend/docs/CAREGIVER_HANDOVER.md buat kontrak lengkapnya.

SEMUA test pakai fixture `client` (SQLite in-memory, lihat
tests/conftest.py), TIDAK PERNAH menyentuh instance/tracker.db asli.
"Sekarang" WAJIB dibekukan lewat `_freeze(monkeypatch)` di SETIAP test
yang bergantung ke waktu — endpoint ini manggil `now_wib()` di layer
route (bukan di utils/caregiver_handover_summary.py), pola SAMA PERSIS
test_reminders.py/test_doctor_consultation.py.
"""
import os
import tempfile
import threading
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

import routes.caregiver_handover_routes as handover_routes_module
from app import create_app
from extensions import db
from models import (
    ActivityLog, CaregiverAuditEvent, CaregiverHandover, CaregiverHandoverAcknowledgement,
    DiaperLog, DoctorVisitLog, FeedingLog, IllnessLog, MedicationDoseAction, MedicationSchedule,
    MoodLog, PumpingLog, Reminder, ReminderAction, SleepLog, TemperatureLog,
)
from tests.conftest import auth_headers, create_child, register
from tests.test_roles_permissions import invite_and_join
from utils.caregiver_handover_engine import NOTE_MAX_LEN

FAKE_NOW = datetime(2026, 8, 23, 14, 30, 0)


def _freeze(monkeypatch, now=FAKE_NOW):
    monkeypatch.setattr(handover_routes_module, "now_wib", lambda: now)


def _get(client, token, child_id):
    return client.get(f"/api/children/{child_id}/caregiver-handover", headers=auth_headers(token))


def _create(client, token, child_id, note=None):
    body = {"note": note} if note is not None else {}
    return client.post(f"/api/children/{child_id}/caregiver-handover", json=body, headers=auth_headers(token))


def _update(client, token, handover_id, note=None):
    body = {"note": note} if note is not None else {"note": None}
    return client.put(f"/api/caregiver-handovers/{handover_id}", json=body, headers=auth_headers(token))


def _acknowledge(client, token, handover_id, body=None):
    return client.post(
        f"/api/caregiver-handovers/{handover_id}/acknowledge", json=body or {}, headers=auth_headers(token),
    )


def _close(client, token, handover_id):
    return client.post(f"/api/caregiver-handovers/{handover_id}/close", json={}, headers=auth_headers(token))


# --------------------------------------------------------------------------
# 1. Model constraints
# --------------------------------------------------------------------------


def test_one_open_handover_per_child_enforced_by_db(client):
    user = register(client)
    child = create_child(client, user["token"])
    now = FAKE_NOW
    db.session.add(CaregiverHandover(
        child_id=child["id"], created_by_user_id=user["id"],
        window_start=now - timedelta(hours=24), as_of_at=now, status="open",
    ))
    db.session.commit()

    db.session.add(CaregiverHandover(
        child_id=child["id"], created_by_user_id=user["id"],
        window_start=now - timedelta(hours=24), as_of_at=now, status="open",
    ))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_second_open_handover_allowed_after_first_closed(client):
    user = register(client)
    child = create_child(client, user["token"])
    now = FAKE_NOW
    first = CaregiverHandover(
        child_id=child["id"], created_by_user_id=user["id"],
        window_start=now - timedelta(hours=24), as_of_at=now, status="closed",
    )
    db.session.add(first)
    db.session.commit()

    db.session.add(CaregiverHandover(
        child_id=child["id"], created_by_user_id=user["id"],
        window_start=now - timedelta(hours=24), as_of_at=now, status="open",
    ))
    db.session.commit()
    assert CaregiverHandover.query.filter_by(child_id=child["id"], status="open").count() == 1


def test_two_open_handovers_allowed_for_different_children(client):
    user = register(client)
    child_a = create_child(client, user["token"], name="A")
    child_b = create_child(client, user["token"], name="B")
    now = FAKE_NOW
    db.session.add(CaregiverHandover(
        child_id=child_a["id"], created_by_user_id=user["id"],
        window_start=now - timedelta(hours=24), as_of_at=now, status="open",
    ))
    db.session.add(CaregiverHandover(
        child_id=child_b["id"], created_by_user_id=user["id"],
        window_start=now - timedelta(hours=24), as_of_at=now, status="open",
    ))
    db.session.commit()
    assert CaregiverHandover.query.filter_by(status="open").count() == 2


def test_status_check_constraint_rejects_invalid_value(client):
    user = register(client)
    child = create_child(client, user["token"])
    now = FAKE_NOW
    db.session.add(CaregiverHandover(
        child_id=child["id"], created_by_user_id=user["id"],
        window_start=now - timedelta(hours=24), as_of_at=now, status="bogus",
    ))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_ack_unique_constraint_enforced_by_db(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]

    db.session.add(CaregiverHandoverAcknowledgement(handover_id=handover_id, user_id=user["id"], acknowledged_at=FAKE_NOW))
    db.session.commit()

    db.session.add(CaregiverHandoverAcknowledgement(handover_id=handover_id, user_id=user["id"], acknowledged_at=FAKE_NOW))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_child_deletion_cascades_handover_and_acknowledgements(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]
    _acknowledge(client, user["token"], handover_id)

    from models import Child
    db.session.delete(Child.query.get(child["id"]))
    db.session.commit()

    assert CaregiverHandover.query.get(handover_id) is None
    assert CaregiverHandoverAcknowledgement.query.filter_by(handover_id=handover_id).count() == 0


# --------------------------------------------------------------------------
# 2. GET — no handover / with handover
# --------------------------------------------------------------------------


def test_get_no_open_handover_returns_null_shape(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _get(client, user["token"], child["id"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["handover"] is None
    assert body["summary"] is None
    assert body["acknowledgements"] == []
    assert body["capabilities"]["can_create"] is True
    assert body["capabilities"]["can_view"] is True


def test_get_unrelated_user_gets_404(client):
    owner = register(client, name="Owner", email="owner-h1@example.com")
    child = create_child(client, owner["token"])
    stranger = register(client, name="Stranger", email="stranger-h1@example.com")
    resp = _get(client, stranger["token"], child["id"])
    assert resp.status_code == 404


def test_get_with_open_handover_includes_summary_and_acknowledgements(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    _create(client, user["token"], child["id"], note="Cek suhu sore ini")

    resp = _get(client, user["token"], child["id"])
    body = resp.get_json()
    assert body["handover"]["status"] == "open"
    assert body["handover"]["note"] == "Cek suhu sore ini"
    assert body["summary"] is not None
    assert body["summary"]["as_of_at"] == FAKE_NOW.isoformat() + "+07:00"
    assert body["acknowledgements"] == []


# --------------------------------------------------------------------------
# 3. POST create — role matrix, race, note validation
# --------------------------------------------------------------------------


def test_owner_can_create(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create(client, user["token"], child["id"])
    assert resp.status_code == 201


def test_editor_can_create(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h2@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-h2@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")
    resp = _create(client, editor["token"], child["id"])
    assert resp.status_code == 201


def test_viewer_cannot_create(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h3@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-h3@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")
    resp = _create(client, viewer["token"], child["id"])
    assert resp.status_code == 403
    assert CaregiverHandover.query.count() == 0


def test_create_when_open_handover_exists_returns_409(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    _create(client, user["token"], child["id"])
    resp = _create(client, user["token"], child["id"])
    assert resp.status_code == 409
    assert CaregiverHandover.query.filter_by(child_id=child["id"], status="open").count() == 1


def test_create_after_close_succeeds(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    first = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]
    _close(client, user["token"], first)
    resp = _create(client, user["token"], child["id"])
    assert resp.status_code == 201


def test_create_freezes_window_from_single_now_wib_sample(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    body = _create(client, user["token"], child["id"]).get_json()["handover"]
    assert body["as_of_at"] == FAKE_NOW.isoformat() + "+07:00"
    assert body["window_start"] == (FAKE_NOW - timedelta(hours=24)).isoformat() + "+07:00"


def test_create_records_exactly_one_audit_event_with_no_note_content(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    before = CaregiverAuditEvent.query.count()
    _create(client, user["token"], child["id"], note="RAHASIA_CATATAN")
    events = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="caregiver_handover").all()
    assert len(events) == 1
    assert events[0].action == "create"
    assert events[0].changed_fields_json is None or "RAHASIA_CATATAN" not in (events[0].changed_fields_json or "")
    assert CaregiverAuditEvent.query.count() == before + 1


def test_create_rejects_note_over_max_length(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create(client, user["token"], child["id"], note="x" * (NOTE_MAX_LEN + 1))
    assert resp.status_code == 400
    assert CaregiverHandover.query.count() == 0


def test_create_note_crlf_normalized_and_trimmed(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create(client, user["token"], child["id"], note="  baris1\r\nbaris2  ")
    assert resp.status_code == 201
    assert resp.get_json()["handover"]["note"] == "baris1\nbaris2"


def test_create_rejects_malformed_json_body(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.post(
        f"/api/children/{child['id']}/caregiver-handover", data="not json", content_type="application/json",
        headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 400
    assert CaregiverHandover.query.count() == 0


def test_create_rejects_non_object_json(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.post(
        f"/api/children/{child['id']}/caregiver-handover", json=["not", "an", "object"],
        headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 400


def test_create_rejects_oversized_declared_body(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    big_note = "x" * 10_000
    resp = _create(client, user["token"], child["id"], note=big_note)
    assert resp.status_code == 413
    assert CaregiverHandover.query.count() == 0


def test_create_cross_child_404(client):
    owner = register(client, name="Owner", email="owner-h4@example.com")
    other_child = create_child(client, owner["token"])
    stranger = register(client, name="Stranger", email="stranger-h4@example.com")
    resp = _create(client, stranger["token"], other_child["id"])
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# 4. PUT update — ownership, closed rejection, no-op audit
# --------------------------------------------------------------------------


def test_owner_can_edit_any_handover(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h5@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-h5@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")
    handover_id = _create(client, editor["token"], child["id"]).get_json()["handover"]["id"]

    resp = _update(client, owner["token"], handover_id, note="diedit owner")
    assert resp.status_code == 200
    assert resp.get_json()["handover"]["note"] == "diedit owner"


def test_editor_can_edit_own_handover(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h6@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-h6@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")
    handover_id = _create(client, editor["token"], child["id"]).get_json()["handover"]["id"]

    resp = _update(client, editor["token"], handover_id, note="diedit editor")
    assert resp.status_code == 200


def test_editor_cannot_edit_another_editors_handover(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h7@example.com")
    child = create_child(client, owner["token"])
    editor1 = register(client, name="Editor1", email="editor1-h7@example.com")
    editor2 = register(client, name="Editor2", email="editor2-h7@example.com")
    invite_and_join(client, owner["token"], child["id"], editor1["token"], "editor")
    invite_and_join(client, owner["token"], child["id"], editor2["token"], "editor")
    handover_id = _create(client, editor1["token"], child["id"]).get_json()["handover"]["id"]

    resp = _update(client, editor2["token"], handover_id, note="nyoba edit punya orang")
    assert resp.status_code == 403


def test_viewer_cannot_edit(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h8@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-h8@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")
    handover_id = _create(client, owner["token"], child["id"]).get_json()["handover"]["id"]

    resp = _update(client, viewer["token"], handover_id, note="nyoba")
    assert resp.status_code == 403


def test_editing_a_closed_handover_is_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]
    _close(client, user["token"], handover_id)

    resp = _update(client, user["token"], handover_id, note="telat")
    assert resp.status_code == 400


def test_no_op_note_update_creates_no_audit_event(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"], note="sama").get_json()["handover"]["id"]

    before = CaregiverAuditEvent.query.filter_by(entity_type="caregiver_handover", action="update").count()
    resp = _update(client, user["token"], handover_id, note="sama")
    assert resp.status_code == 200
    after = CaregiverAuditEvent.query.filter_by(entity_type="caregiver_handover", action="update").count()
    assert after == before


def test_actual_note_update_creates_exactly_one_audit_event(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"], note="lama").get_json()["handover"]["id"]

    before = CaregiverAuditEvent.query.filter_by(entity_type="caregiver_handover", action="update").count()
    _update(client, user["token"], handover_id, note="baru")
    after = CaregiverAuditEvent.query.filter_by(entity_type="caregiver_handover", action="update").count()
    assert after == before + 1


def test_update_cross_child_unrelated_user_404(client):
    owner = register(client, name="Owner", email="owner-h9@example.com")
    child = create_child(client, owner["token"])
    handover_id = _create(client, owner["token"], child["id"]).get_json()["handover"]["id"]
    stranger = register(client, name="Stranger", email="stranger-h9@example.com")
    resp = _update(client, stranger["token"], handover_id, note="x")
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# 5. Acknowledge — idempotency, roles, close independence
# --------------------------------------------------------------------------


def test_every_role_can_acknowledge_including_viewer(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h10@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-h10@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")
    handover_id = _create(client, owner["token"], child["id"]).get_json()["handover"]["id"]

    resp = _acknowledge(client, viewer["token"], handover_id)
    assert resp.status_code == 201
    assert resp.get_json()["created"] is True


def test_acknowledge_is_idempotent_per_user(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]

    first = _acknowledge(client, user["token"], handover_id)
    assert first.status_code == 201
    assert first.get_json()["created"] is True

    second = _acknowledge(client, user["token"], handover_id)
    assert second.status_code == 200
    assert second.get_json()["created"] is False
    assert CaregiverHandoverAcknowledgement.query.filter_by(handover_id=handover_id, user_id=user["id"]).count() == 1


def test_acknowledge_records_exactly_one_audit_event_on_first_success(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]

    before = CaregiverAuditEvent.query.filter_by(entity_type="caregiver_handover_acknowledged").count()
    _acknowledge(client, user["token"], handover_id)
    _acknowledge(client, user["token"], handover_id)
    after = CaregiverAuditEvent.query.filter_by(entity_type="caregiver_handover_acknowledged").count()
    assert after == before + 1


def test_acknowledge_display_shows_name_and_timestamp_only(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client, name="Nama Pengasuh", email="ack-fields@example.com")
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]
    _acknowledge(client, user["token"], handover_id)

    body = _get(client, user["token"], child["id"]).get_json()
    ack = body["acknowledgements"][0]
    assert ack["display_name"] == "Nama Pengasuh"
    assert "acknowledged_at" in ack
    assert set(ack.keys()) == {"id", "user_id", "display_name", "acknowledged_at"}
    assert "email" not in ack


def test_acknowledge_still_allowed_after_close(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h11@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-h11@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")
    handover_id = _create(client, owner["token"], child["id"]).get_json()["handover"]["id"]
    _close(client, owner["token"], handover_id)

    resp = _acknowledge(client, viewer["token"], handover_id)
    assert resp.status_code == 201


def test_removed_caregiver_cannot_acknowledge(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h12@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-h12@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")
    handover_id = _create(client, owner["token"], child["id"]).get_json()["handover"]["id"]

    from models import ChildCaregiver
    ChildCaregiver.query.filter_by(child_id=child["id"], user_id=editor["id"]).delete()
    db.session.commit()

    resp = _acknowledge(client, editor["token"], handover_id)
    assert resp.status_code == 404


def test_acknowledge_cross_child_404(client):
    owner = register(client, name="Owner", email="owner-h13@example.com")
    child = create_child(client, owner["token"])
    handover_id = _create(client, owner["token"], child["id"]).get_json()["handover"]["id"]
    stranger = register(client, name="Stranger", email="stranger-h13@example.com")
    resp = _acknowledge(client, stranger["token"], handover_id)
    assert resp.status_code == 404


def test_acknowledge_rejects_oversized_body(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]
    resp = client.post(
        f"/api/caregiver-handovers/{handover_id}/acknowledge",
        json={"padding": "x" * 500}, headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 413


# --------------------------------------------------------------------------
# 6. Close — idempotency, ownership, roles
# --------------------------------------------------------------------------


def test_owner_can_close_any_handover(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h14@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-h14@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")
    handover_id = _create(client, editor["token"], child["id"]).get_json()["handover"]["id"]

    resp = _close(client, owner["token"], handover_id)
    assert resp.status_code == 200
    assert resp.get_json()["handover"]["status"] == "closed"


def test_editor_can_close_own_but_not_others(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h15@example.com")
    child = create_child(client, owner["token"])
    editor1 = register(client, name="Editor1", email="editor1-h15@example.com")
    editor2 = register(client, name="Editor2", email="editor2-h15@example.com")
    invite_and_join(client, owner["token"], child["id"], editor1["token"], "editor")
    invite_and_join(client, owner["token"], child["id"], editor2["token"], "editor")
    handover_id = _create(client, editor1["token"], child["id"]).get_json()["handover"]["id"]

    denied = _close(client, editor2["token"], handover_id)
    assert denied.status_code == 403

    allowed = _close(client, editor1["token"], handover_id)
    assert allowed.status_code == 200


def test_viewer_cannot_close(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h16@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-h16@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")
    handover_id = _create(client, owner["token"], child["id"]).get_json()["handover"]["id"]

    resp = _close(client, viewer["token"], handover_id)
    assert resp.status_code == 403


def test_second_close_is_idempotent_not_500(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]

    first = _close(client, user["token"], handover_id)
    second = _close(client, user["token"], handover_id)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()["handover"]["status"] == "closed"


def test_close_creates_exactly_one_audit_event_even_with_repeats(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]

    before = CaregiverAuditEvent.query.filter_by(entity_type="caregiver_handover_closed").count()
    _close(client, user["token"], handover_id)
    _close(client, user["token"], handover_id)
    _close(client, user["token"], handover_id)
    after = CaregiverAuditEvent.query.filter_by(entity_type="caregiver_handover_closed").count()
    assert after == before + 1


def test_close_allows_new_handover_afterwards(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]
    _close(client, user["token"], handover_id)

    resp = _create(client, user["token"], child["id"])
    assert resp.status_code == 201


def test_close_cross_child_404(client):
    owner = register(client, name="Owner", email="owner-h17@example.com")
    child = create_child(client, owner["token"])
    handover_id = _create(client, owner["token"], child["id"]).get_json()["handover"]["id"]
    stranger = register(client, name="Stranger", email="stranger-h17@example.com")
    resp = _close(client, stranger["token"], handover_id)
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# 7. Capabilities — never trust frontend, always recomputed
# --------------------------------------------------------------------------


def test_capabilities_reflect_editor_ownership(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h18@example.com")
    child = create_child(client, owner["token"])
    editor1 = register(client, name="Editor1", email="editor1-h18@example.com")
    editor2 = register(client, name="Editor2", email="editor2-h18@example.com")
    invite_and_join(client, owner["token"], child["id"], editor1["token"], "editor")
    invite_and_join(client, owner["token"], child["id"], editor2["token"], "editor")
    _create(client, editor1["token"], child["id"])

    caps1 = _get(client, editor1["token"], child["id"]).get_json()["capabilities"]
    caps2 = _get(client, editor2["token"], child["id"]).get_json()["capabilities"]
    assert caps1["can_edit"] is True and caps1["can_close"] is True
    assert caps2["can_edit"] is False and caps2["can_close"] is False
    assert caps1["can_acknowledge"] is True and caps2["can_acknowledge"] is True


def test_capabilities_after_closed_disallow_edit_and_close(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]
    _close(client, user["token"], handover_id)

    caps = _get(client, user["token"], child["id"]).get_json()["capabilities"]
    assert caps["can_create"] is True


def test_viewer_capabilities_view_and_ack_only(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Owner", email="owner-h19@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-h19@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")
    _create(client, owner["token"], child["id"])

    caps = _get(client, viewer["token"], child["id"]).get_json()["capabilities"]
    assert caps["can_view"] is True
    assert caps["can_create"] is False
    assert caps["can_edit"] is False
    assert caps["can_close"] is False
    assert caps["can_acknowledge"] is True


# --------------------------------------------------------------------------
# 8. Summary sections — measured completeness, missing data, isolation
# --------------------------------------------------------------------------


def _seed_and_get_summary(client, monkeypatch, token, child_id):
    _freeze(monkeypatch)
    resp = _create(client, token, child_id)
    return resp.get_json()["summary"]


def test_feeding_section_conservative_total_all_measured(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(FeedingLog(child_id=child["id"], timestamp=FAKE_NOW - timedelta(hours=2), feed_type="sufor", volume_ml=100))
    db.session.add(FeedingLog(child_id=child["id"], timestamp=FAKE_NOW - timedelta(hours=1), feed_type="sufor", volume_ml=120))
    db.session.commit()

    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    assert summary["feeding"]["total_events"] == 2
    assert summary["feeding"]["measured_total_volume_ml"] == 220
    assert summary["feeding"]["latest_volume_ml"] == 120


def test_feeding_section_total_is_none_when_partially_measured(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(FeedingLog(child_id=child["id"], timestamp=FAKE_NOW - timedelta(hours=2), feed_type="asi_langsung", volume_ml=None))
    db.session.add(FeedingLog(child_id=child["id"], timestamp=FAKE_NOW - timedelta(hours=1), feed_type="sufor", volume_ml=120))
    db.session.commit()

    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    assert summary["feeding"]["measured_total_volume_ml"] is None


def test_feeding_section_empty_state_is_explicit_null_not_zero_lie(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    assert summary["feeding"]["total_events"] == 0
    # 0 event -> total 0 TERPERCAYA PENUH (bukan data hilang, lihat
    # _measured_total_or_none) -- yang jadi None cuma kasus SEBAGIAN
    # terukur (lihat test_feeding_section_total_is_none_when_partially_measured).
    assert summary["feeding"]["measured_total_volume_ml"] == 0
    assert summary["feeding"]["latest_timestamp"] is None


def test_feeding_section_outside_window_excluded(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    outside = FAKE_NOW - timedelta(hours=25)
    db.session.add(FeedingLog(child_id=child["id"], timestamp=outside, feed_type="sufor", volume_ml=100))
    db.session.commit()

    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    assert summary["feeding"]["total_events"] == 0


def test_sleep_section_ongoing_and_completed_minutes(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(SleepLog(
        child_id=child["id"], start_time=FAKE_NOW - timedelta(hours=3),
        end_time=FAKE_NOW - timedelta(hours=2), sleep_type="siang",
    ))
    db.session.add(SleepLog(child_id=child["id"], start_time=FAKE_NOW - timedelta(minutes=30), end_time=None, sleep_type="malam"))
    db.session.commit()

    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    assert summary["sleep"]["total_events"] == 2
    assert summary["sleep"]["latest_is_ongoing"] is True
    assert summary["sleep"]["total_completed_minutes"] == 60.0


def test_diaper_section_counts(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(DiaperLog(child_id=child["id"], timestamp=FAKE_NOW - timedelta(hours=1), diaper_type="pipis"))
    db.session.add(DiaperLog(child_id=child["id"], timestamp=FAKE_NOW - timedelta(hours=2), diaper_type="pup"))
    db.session.add(DiaperLog(child_id=child["id"], timestamp=FAKE_NOW - timedelta(hours=3), diaper_type="keduanya"))
    db.session.commit()

    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    assert summary["diaper"]["wet_count"] == 2
    assert summary["diaper"]["dirty_count"] == 2
    assert summary["diaper"]["mixed_count"] == 1


def test_pumping_section_measured_total(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(PumpingLog(child_id=child["id"], timestamp=FAKE_NOW - timedelta(hours=1), volume_ml=80))
    db.session.commit()

    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    assert summary["pumping"]["measured_total_volume_ml"] == 80


def test_activity_mood_section_latest_of_each(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(ActivityLog(child_id=child["id"], activity_type="stroll", timestamp=FAKE_NOW - timedelta(hours=1)))
    db.session.add(MoodLog(child_id=child["id"], mood="ceria", timestamp=FAKE_NOW - timedelta(hours=2)))
    db.session.commit()

    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    assert summary["activity_mood"]["latest_activity_type"] == "stroll"
    assert summary["activity_mood"]["latest_mood"] == "ceria"


def test_health_section_excludes_illness_name_includes_dates_only(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(TemperatureLog(child_id=child["id"], timestamp=FAKE_NOW - timedelta(hours=1), temperature_celsius=37.9))
    db.session.add(IllnessLog(
        child_id=child["id"], illness_name="RAHASIA_PENYAKIT",
        start_date=FAKE_NOW.date() - timedelta(days=1), end_date=None,
    ))
    db.session.add(DoctorVisitLog(
        child_id=child["id"], visit_date=FAKE_NOW.date(), reason="demam",
        doctor_name="RAHASIA_DOKTER", diagnosis="RAHASIA_DIAGNOSIS",
    ))
    db.session.commit()

    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    health = summary["health"]
    assert health["latest_temperature_celsius"] == 37.9
    illness = health["illnesses_overlapping_window"][0]
    assert set(illness.keys()) == {"start_date", "end_date", "is_ongoing"}
    assert "RAHASIA_PENYAKIT" not in str(summary)
    assert health["latest_doctor_visit_reason"] == "demam"
    assert "RAHASIA_DOKTER" not in str(summary)
    assert "RAHASIA_DIAGNOSIS" not in str(summary)


def test_summary_never_includes_free_text_notes(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(FeedingLog(
        child_id=child["id"], timestamp=FAKE_NOW - timedelta(hours=1), feed_type="sufor",
        volume_ml=100, notes="RAHASIA_CATATAN_MENYUSUI",
    ))
    db.session.commit()

    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    assert "RAHASIA_CATATAN_MENYUSUI" not in str(summary)


def test_summary_isolated_from_other_childrens_data(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child_a = create_child(client, user["token"], name="A")
    child_b = create_child(client, user["token"], name="B")
    db.session.add(FeedingLog(child_id=child_b["id"], timestamp=FAKE_NOW - timedelta(hours=1), feed_type="sufor", volume_ml=999))
    db.session.commit()

    summary = _create(client, user["token"], child_a["id"]).get_json()["summary"]
    assert summary["feeding"]["total_events"] == 0


def test_no_diagnosis_or_medical_advice_keywords_in_summary(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    # "diagnos" SENGAJA muncul di `disclaimer` (menegaskan ini BUKAN
    # diagnosis) -- dikecualikan dari scan, sisanya (isi ringkasan per
    # kategori) TIDAK BOLEH pernah menyebutnya.
    sections_only = {k: v for k, v in summary.items() if k not in ("disclaimer", "privacy_note")}
    text = str(sections_only).lower()
    for banned in ("diagnos", "resep", "obati sendiri", "rekomendasi tindakan"):
        assert banned not in text
    assert "bukan" in summary["disclaimer"].lower()
    assert "diagnos" in summary["disclaimer"].lower()


# --------------------------------------------------------------------------
# 9. Medication / reminder sections — reuse engine, overdue/next
# --------------------------------------------------------------------------


def test_medication_section_administered_dose_in_window(client, monkeypatch):
    _freeze(monkeypatch)
    monkeypatch.setattr("routes.medication_schedule_routes.now_wib", lambda: FAKE_NOW)
    user = register(client)
    child = create_child(client, user["token"])
    sched_resp = client.post(
        f"/api/children/{child['id']}/medication-schedules",
        json={
            "medication_name": "Paracetamol", "dose_value": 5, "dose_unit": "ml",
            "times_of_day": ["08:00"], "start_date": FAKE_NOW.date().isoformat(),
        },
        headers=auth_headers(user["token"]),
    )
    assert sched_resp.status_code == 201, sched_resp.get_json()
    schedule_id = sched_resp.get_json()["id"]
    occ_key = f"{FAKE_NOW.date().isoformat()}T08:00"
    act_resp = client.post(
        f"/api/children/{child['id']}/medication-schedules/{schedule_id}/occurrences/{occ_key}/administer",
        json={}, headers=auth_headers(user["token"]),
    )
    assert act_resp.status_code == 201, act_resp.get_json()

    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    med = summary["medication"]
    assert len(med["administered_in_window"]) == 1
    assert med["administered_in_window"][0]["medication_name"] == "Paracetamol"
    assert med["administered_in_window"][0]["dose"] == "5 ml"


def test_medication_section_overdue_dose(client, monkeypatch):
    _freeze(monkeypatch)
    monkeypatch.setattr("routes.medication_schedule_routes.now_wib", lambda: FAKE_NOW)
    user = register(client)
    child = create_child(client, user["token"])
    sched_resp = client.post(
        f"/api/children/{child['id']}/medication-schedules",
        json={
            "medication_name": "Vitamin D", "dose_value": 1, "dose_unit": "tetes",
            "times_of_day": ["07:00"], "start_date": FAKE_NOW.date().isoformat(),
        },
        headers=auth_headers(user["token"]),
    )
    assert sched_resp.status_code == 201, sched_resp.get_json()

    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    overdue_names = [e["medication_name"] for e in summary["medication"]["overdue_as_of_as_of_at"]]
    assert "Vitamin D" in overdue_names


def test_medication_section_no_medications_returns_empty_lists(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    assert summary["medication"]["administered_in_window"] == []
    assert summary["medication"]["overdue_as_of_as_of_at"] == []
    assert summary["medication"]["next_occurrence"] is None


def test_reminder_section_overdue_reminder(client, monkeypatch):
    _freeze(monkeypatch)
    monkeypatch.setattr("routes.reminder_routes.now_wib", lambda: FAKE_NOW)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.post(
        f"/api/children/{child['id']}/reminders",
        json={
            "reminder_type": "medication", "title": "RAHASIA_TITLE_JUDUL",
            "scheduled_at": (FAKE_NOW - timedelta(hours=2)).isoformat(), "recurrence": "none",
        },
        headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 201, resp.get_json()

    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    overdue = summary["reminders"]["overdue_as_of_as_of_at"]
    assert len(overdue) == 1
    assert overdue[0]["reminder_type"] == "medication"


def test_reminder_section_no_reminders_returns_empty(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    summary = _create(client, user["token"], child["id"]).get_json()["summary"]
    assert summary["reminders"]["overdue_as_of_as_of_at"] == []
    assert summary["reminders"]["resolved_in_window"] == []
    assert summary["reminders"]["next_occurrence"] is None


# --------------------------------------------------------------------------
# 10. Missing Content-Length / boundary body-size tests (PUT)
# --------------------------------------------------------------------------


def test_update_rejects_oversized_body(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]

    resp = _update(client, user["token"], handover_id, note="x" * 10_000)
    assert resp.status_code == 413


def test_update_rejects_malformed_json(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]

    resp = client.put(
        f"/api/caregiver-handovers/{handover_id}", data="{not valid", content_type="application/json",
        headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# 11. Real concurrency (genuine threads, file-based SQLite + NullPool —
# pola SAMA PERSIS tests/test_concurrency.py)
# --------------------------------------------------------------------------


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


def test_concurrent_creates_yield_exactly_one_open_handover(file_db_app, monkeypatch):
    monkeypatch.setattr(handover_routes_module, "now_wib", lambda: FAKE_NOW)
    client = file_db_app.test_client()
    user = register(client)
    child = create_child(client, user["token"])

    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        with file_db_app.test_client() as c:
            resp = _create(c, user["token"], child["id"])
            results.append(resp.status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with file_db_app.app_context():
        assert sorted(results) == [201, 409]
        assert CaregiverHandover.query.filter_by(child_id=child["id"], status="open").count() == 1


def test_concurrent_acknowledgements_from_same_user_yield_one_row(file_db_app, monkeypatch):
    monkeypatch.setattr(handover_routes_module, "now_wib", lambda: FAKE_NOW)
    client = file_db_app.test_client()
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]

    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        with file_db_app.test_client() as c:
            resp = _acknowledge(c, user["token"], handover_id)
            results.append(resp.status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with file_db_app.app_context():
        assert sorted(results) == [200, 201]
        assert CaregiverHandoverAcknowledgement.query.filter_by(
            handover_id=handover_id, user_id=user["id"],
        ).count() == 1


def test_close_racing_with_acknowledge_is_deterministic(file_db_app, monkeypatch):
    monkeypatch.setattr(handover_routes_module, "now_wib", lambda: FAKE_NOW)
    client = file_db_app.test_client()
    user = register(client)
    child = create_child(client, user["token"])
    handover_id = _create(client, user["token"], child["id"]).get_json()["handover"]["id"]

    results = {}
    barrier = threading.Barrier(2)

    def close_worker():
        barrier.wait()
        with file_db_app.test_client() as c:
            results["close"] = _close(c, user["token"], handover_id).status_code

    def ack_worker():
        barrier.wait()
        with file_db_app.test_client() as c:
            results["ack"] = _acknowledge(c, user["token"], handover_id).status_code

    t1 = threading.Thread(target=close_worker)
    t2 = threading.Thread(target=ack_worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results["close"] == 200
    assert results["ack"] in (200, 201)
    with file_db_app.app_context():
        assert CaregiverHandover.query.get(handover_id).status == "closed"
        assert CaregiverHandoverAcknowledgement.query.filter_by(handover_id=handover_id).count() == 1


# --------------------------------------------------------------------------
# 12. Regression checks — other features unaffected
# --------------------------------------------------------------------------


def test_reminder_endpoints_still_work_after_handover_feature_added(client, monkeypatch):
    monkeypatch.setattr("routes.reminder_routes.now_wib", lambda: FAKE_NOW)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.get(f"/api/children/{child['id']}/reminders", headers=auth_headers(user["token"]))
    assert resp.status_code == 200


def test_medication_schedule_endpoints_still_work(client, monkeypatch):
    monkeypatch.setattr("routes.medication_schedule_routes.now_wib", lambda: FAKE_NOW)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.get(f"/api/children/{child['id']}/medication-schedules", headers=auth_headers(user["token"]))
    assert resp.status_code == 200


def test_audit_trail_endpoint_lists_caregiver_handover_entity_type(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    _create(client, user["token"], child["id"])
    resp = client.get(
        f"/api/children/{child['id']}/audit-events?entity_type=caregiver_handover",
        headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 200


def test_insights_endpoint_still_works(client, monkeypatch):
    monkeypatch.setattr("routes.insights_routes.now_wib", lambda: FAKE_NOW, raising=False)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.get(f"/api/children/{child['id']}/insights", headers=auth_headers(user["token"]))
    assert resp.status_code == 200


def test_roles_permissions_endpoints_unaffected(client):
    owner = register(client, name="Owner", email="owner-h20@example.com")
    child = create_child(client, owner["token"])
    resp = client.get(f"/api/children/{child['id']}", headers=auth_headers(owner["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["role"] == "owner"
