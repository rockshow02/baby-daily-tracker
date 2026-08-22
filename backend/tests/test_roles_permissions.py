"""
Test Caregiver Roles & Permissions Phase 1 — model peran (owner/editor/
viewer), otorisasi terpusat (utils/access.py), endpoint kelola caregiver
(undang/ubah peran/cabut), dan integrasi audit trail membership.

SEMUA test pakai fixture `client` (SQLite in-memory), TIDAK PERNAH
menyentuh instance/tracker.db asli. Lihat backend/docs/ROLES_PERMISSIONS.md
buat matriks izin lengkapnya.
"""
import pytest

from extensions import db
from models import CaregiverAuditEvent, ChildCaregiver, FeedingLog
from tests.conftest import auth_headers, create_child, register
from tests.test_audit_trail import ENTITY_SPECS, ENTITY_TYPES, _create, _update, _delete, _list_events


def invite(client, owner_token, child_id, role):
    resp = client.post(f"/api/children/{child_id}/invite", json={"role": role}, headers=auth_headers(owner_token))
    return resp


def join(client, token, code):
    return client.post("/api/children/join", json={"code": code}, headers=auth_headers(token))


def invite_and_join(client, owner_token, child_id, joiner_token, role):
    inv = invite(client, owner_token, child_id, role)
    assert inv.status_code == 201, inv.get_json()
    j = join(client, joiner_token, inv.get_json()["code"])
    assert j.status_code == 201, j.get_json()
    return j.get_json()


def two_users_with_child(client, role="editor"):
    """(owner, caregiver, child) — caregiver udah gabung dengan `role`."""
    owner = register(client, name="Pemilik", email="owner-rp@example.com")
    child = create_child(client, owner["token"])
    caregiver = register(client, name="Pengasuh", email="caregiver-rp@example.com")
    invite_and_join(client, owner["token"], child["id"], caregiver["token"], role)
    return owner, caregiver, child


# --------------------------------------------------------------------------
# 1. Owner resolves as owner / 2. Migrated caregivers become editors
# (migrasi sungguhan dites di test_migrate_production.py — di sini CUMA
# dites lewat API: hasil `add_caregiver()` default, yang setara "caregiver
# lama", HARUS berperilaku sebagai editor).
# --------------------------------------------------------------------------


def test_owner_resolves_as_owner(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = client.get(f"/api/children/{child['id']}", headers=auth_headers(owner["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["role"] == "owner"


def test_default_add_caregiver_role_behaves_like_legacy_caregiver_ie_editor(client):
    owner, caregiver, child = two_users_with_child(client)  # role="editor" default
    resp = client.get(f"/api/children/{child['id']}", headers=auth_headers(caregiver["token"]))
    assert resp.status_code == 200
    assert resp.get_json()["role"] == "editor"


# --------------------------------------------------------------------------
# 3/4. Invitation acceptance preserves owner-selected role; accepting user
# cannot override it.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("chosen_role", ["editor", "viewer"])
def test_invitation_acceptance_preserves_owner_selected_role(client, chosen_role):
    owner = register(client, name="O", email=f"o-{chosen_role}@example.com")
    child = create_child(client, owner["token"])
    joiner = register(client, name="J", email=f"j-{chosen_role}@example.com")
    result = invite_and_join(client, owner["token"], child["id"], joiner["token"], chosen_role)
    assert result["child"]["role"] == chosen_role

    cc = ChildCaregiver.query.filter_by(child_id=child["id"], user_id=joiner["id"]).first()
    assert cc.role == chosen_role


def test_accepting_user_cannot_override_invitation_role(client):
    owner = register(client, name="O2", email="o2@example.com")
    child = create_child(client, owner["token"])
    joiner = register(client, name="J2", email="j2@example.com")
    inv = invite(client, owner["token"], child["id"], "viewer")
    assert inv.status_code == 201

    # joiner nyoba nyelundupin role="editor" di body join — HARUS diabaikan
    resp = client.post(
        "/api/children/join",
        json={"code": inv.get_json()["code"], "role": "editor"},
        headers=auth_headers(joiner["token"]),
    )
    assert resp.status_code == 201
    assert resp.get_json()["child"]["role"] == "viewer"
    cc = ChildCaregiver.query.filter_by(child_id=child["id"], user_id=joiner["id"]).first()
    assert cc.role == "viewer"


# --------------------------------------------------------------------------
# 5. Invalid roles rejected — undangan & ubah peran.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad_role", ["owner", "admin", "", None, 123, "Editor", "EDITOR"])
def test_invalid_roles_are_rejected_on_invite(client, bad_role):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = invite(client, owner["token"], child["id"], bad_role)
    assert resp.status_code == 400


def test_invite_without_role_field_is_rejected(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    resp = client.post(f"/api/children/{child['id']}/invite", json={}, headers=auth_headers(owner["token"]))
    assert resp.status_code == 400


@pytest.mark.parametrize("bad_role", ["owner", "admin", "", None, 123])
def test_invalid_roles_are_rejected_on_role_change(client, bad_role):
    owner, caregiver, child = two_users_with_child(client)
    resp = client.put(
        f"/api/children/{child['id']}/caregivers/{caregiver['id']}",
        json={"role": bad_role},
        headers=auth_headers(owner["token"]),
    )
    assert resp.status_code == 400
    cc = ChildCaregiver.query.filter_by(child_id=child["id"], user_id=caregiver["id"]).first()
    assert cc.role == "editor"  # nggak berubah


# --------------------------------------------------------------------------
# 6-9. Viewer: baca semua boleh, tulis (create/update/delete) semua ditolak.
# --------------------------------------------------------------------------


VIEWER_READ_ENDPOINTS = [
    lambda cid: f"/api/children/{cid}",
    lambda cid: f"/api/children/{cid}/feeding-logs",
    lambda cid: f"/api/children/{cid}/sleep-logs",
    lambda cid: f"/api/children/{cid}/diaper-logs",
    lambda cid: f"/api/children/{cid}/pumping-logs",
    lambda cid: f"/api/children/{cid}/activity-logs",
    lambda cid: f"/api/children/{cid}/growth-measurements",
    lambda cid: f"/api/children/{cid}/doctor-visits",
    lambda cid: f"/api/children/{cid}/temperature-logs",
    lambda cid: f"/api/children/{cid}/illness-logs",
    lambda cid: f"/api/children/{cid}/medication-logs",
    lambda cid: f"/api/children/{cid}/mood-logs",
    lambda cid: f"/api/children/{cid}/milestone-logs",
    lambda cid: f"/api/children/{cid}/daily-summary",
    lambda cid: f"/api/children/{cid}/audit-events",
    lambda cid: f"/api/children/{cid}/caregivers",
    lambda cid: f"/api/children/{cid}/vaccinations",
]


@pytest.mark.parametrize("path_fn", VIEWER_READ_ENDPOINTS)
def test_viewer_can_read_every_relevant_child_scoped_resource(client, path_fn):
    owner, viewer, child = two_users_with_child(client, role="viewer")
    resp = client.get(path_fn(child["id"]), headers=auth_headers(viewer["token"]))
    assert resp.status_code == 200, (path_fn(child["id"]), resp.get_json())


@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
def test_viewer_cannot_create_any_supported_record_type(client, entity_type):
    owner, viewer, child = two_users_with_child(client, role="viewer")
    spec = ENTITY_SPECS[entity_type]
    headers = auth_headers(viewer["token"])
    if spec["idempotent"]:
        headers = {**headers, "X-Idempotency-Key": "viewer-create-key"}
    resp = client.post(
        f"/api/children/{child['id']}/{spec['create_path']}", json=spec["create_payload"], headers=headers
    )
    assert resp.status_code == 403


@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
def test_viewer_cannot_update_any_supported_record_type(client, entity_type):
    owner, viewer, child = two_users_with_child(client, role="viewer")
    created = _create(client, owner["token"], child["id"], entity_type, idem_key="k1")
    spec = ENTITY_SPECS[entity_type]
    resp = client.put(
        f"/api/{spec['item_path']}/{created['id']}", json=spec["meaningful_update"], headers=auth_headers(viewer["token"])
    )
    assert resp.status_code == 403

    events = _list_events(client, owner["token"], child["id"]).get_json()["events"]
    assert [e["action"] for e in events if e["entity_type"] == entity_type] == ["create"]


@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
def test_viewer_cannot_delete_any_supported_record_type(client, entity_type):
    owner, viewer, child = two_users_with_child(client, role="viewer")
    created = _create(client, owner["token"], child["id"], entity_type, idem_key="k1")
    spec = ENTITY_SPECS[entity_type]
    resp = client.delete(f"/api/{spec['item_path']}/{created['id']}", headers=auth_headers(viewer["token"]))
    assert resp.status_code == 403

    events = _list_events(client, owner["token"], child["id"]).get_json()["events"]
    assert [e["action"] for e in events if e["entity_type"] == entity_type] == ["create"]


# --------------------------------------------------------------------------
# 10-14. Editor create/update; delete-ownership rules; owner can delete
# anything.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
def test_editor_can_create_and_update_all_supported_record_types(client, entity_type):
    owner, editor, child = two_users_with_child(client, role="editor")
    spec = ENTITY_SPECS[entity_type]
    created = _create(client, editor["token"], child["id"], entity_type, idem_key="k1")
    updated = _update(client, editor["token"], entity_type, created["id"], spec["meaningful_update"])
    assert updated["id"] == created["id"]


@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
def test_editor_can_delete_their_own_records(client, entity_type):
    owner, editor, child = two_users_with_child(client, role="editor")
    created = _create(client, editor["token"], child["id"], entity_type, idem_key="k1")
    _delete(client, editor["token"], entity_type, created["id"])  # asserts 200 inside helper


@pytest.mark.parametrize("entity_type", ENTITY_TYPES)
def test_editor_cannot_delete_records_created_by_owner(client, entity_type):
    owner, editor, child = two_users_with_child(client, role="editor")
    created = _create(client, owner["token"], child["id"], entity_type, idem_key="k1")
    spec = ENTITY_SPECS[entity_type]
    resp = client.delete(f"/api/{spec['item_path']}/{created['id']}", headers=auth_headers(editor["token"]))
    assert resp.status_code == 403


def test_editor_cannot_delete_records_created_by_another_caregiver(client):
    owner = register(client, name="O3", email="o3@example.com")
    child = create_child(client, owner["token"])
    editor_a = register(client, name="EA", email="ea@example.com")
    editor_b = register(client, name="EB", email="eb@example.com")
    invite_and_join(client, owner["token"], child["id"], editor_a["token"], "editor")
    invite_and_join(client, owner["token"], child["id"], editor_b["token"], "editor")

    created = _create(client, editor_a["token"], child["id"], "feeding_log", idem_key="k1")
    resp = client.delete(f"/api/feeding-logs/{created['id']}", headers=auth_headers(editor_b["token"]))
    assert resp.status_code == 403


@pytest.mark.parametrize("entity_type", ["feeding_log", "growth_measurement", "medication_log"])
def test_editor_cannot_delete_a_legacy_record_with_null_creator(client, entity_type):
    owner, editor, child = two_users_with_child(client, role="editor")
    created = _create(client, owner["token"], child["id"], entity_type, idem_key="k1")
    spec = ENTITY_SPECS[entity_type]
    # simulasiin record legacy: created_by_user_id di-null-kan langsung di DB
    model_map = {"feeding_log": FeedingLog}
    if entity_type in model_map:
        row = model_map[entity_type].query.get(created["id"])
        row.created_by_user_id = None
        db.session.commit()
    else:
        from models import GrowthMeasurement, MedicationLog
        model = {"growth_measurement": GrowthMeasurement, "medication_log": MedicationLog}[entity_type]
        row = model.query.get(created["id"])
        row.created_by_user_id = None
        db.session.commit()

    resp = client.delete(f"/api/{spec['item_path']}/{created['id']}", headers=auth_headers(editor["token"]))
    assert resp.status_code == 403


def test_owner_can_delete_records_created_by_anyone_and_legacy_records(client):
    owner, editor, child = two_users_with_child(client, role="editor")
    by_editor = _create(client, editor["token"], child["id"], "feeding_log", idem_key="k1")
    _delete(client, owner["token"], "feeding_log", by_editor["id"])

    by_owner = _create(client, owner["token"], child["id"], "feeding_log", idem_key="k2")
    row = FeedingLog.query.get(by_owner["id"])
    row.created_by_user_id = None
    db.session.commit()
    _delete(client, owner["token"], "feeding_log", by_owner["id"])


# --------------------------------------------------------------------------
# 15-16. Owner-only: edit/hapus anak, kelola caregiver.
# --------------------------------------------------------------------------


OWNER_ONLY_ACTION_NAMES = ["PUT_CHILD", "DELETE_CHILD", "INVITE"]


@pytest.mark.parametrize("role", ["editor", "viewer"])
@pytest.mark.parametrize("action_name", OWNER_ONLY_ACTION_NAMES)
def test_only_owner_can_edit_delete_child_or_create_invites(client, role, action_name):
    owner, member, child = two_users_with_child(client, role=role)
    headers = auth_headers(member["token"])
    if action_name == "PUT_CHILD":
        resp = client.put(f"/api/children/{child['id']}", json={"name": "Baru"}, headers=headers)
    elif action_name == "DELETE_CHILD":
        resp = client.delete(f"/api/children/{child['id']}", headers=headers)
    else:
        resp = client.post(f"/api/children/{child['id']}/invite", json={"role": "editor"}, headers=headers)
    assert resp.status_code == 403


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_editor_and_viewer_cannot_change_roles_or_revoke_access(client, role):
    owner, member, child = two_users_with_child(client, role=role)
    other = register(client, name="Other", email=f"other-{role}@example.com")
    invite_and_join(client, owner["token"], child["id"], other["token"], "viewer")

    resp = client.put(
        f"/api/children/{child['id']}/caregivers/{other['id']}", json={"role": "editor"}, headers=auth_headers(member["token"])
    )
    assert resp.status_code == 403

    resp2 = client.delete(f"/api/children/{child['id']}/caregivers/{other['id']}", headers=auth_headers(member["token"]))
    assert resp2.status_code == 403


# --------------------------------------------------------------------------
# 17. Caregiver nggak bisa naikin peran sendiri lewat input yang direkayasa.
# --------------------------------------------------------------------------


def test_caregiver_cannot_escalate_their_own_role(client):
    owner, viewer, child = two_users_with_child(client, role="viewer")

    # viewer nyoba PUT role dirinya sendiri (endpoint ini owner-only,
    # jadi ditolak duluan sebelum sempat ngecek isi body)
    resp = client.put(
        f"/api/children/{child['id']}/caregivers/{viewer['id']}", json={"role": "editor"}, headers=auth_headers(viewer["token"])
    )
    assert resp.status_code == 403

    cc = ChildCaregiver.query.filter_by(child_id=child["id"], user_id=viewer["id"]).first()
    assert cc.role == "viewer"


def test_owner_cannot_change_their_own_role_via_the_endpoint(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    # owner nggak punya baris ChildCaregiver -> endpoint ini bakal balikin
    # 400 (guard eksplisit "pemilik tidak bisa ubah perannya sendiri")
    resp = client.put(
        f"/api/children/{child['id']}/caregivers/{owner['id']}", json={"role": "editor"}, headers=auth_headers(owner["token"])
    )
    assert resp.status_code == 400


def test_role_change_endpoint_rejects_assigning_owner(client):
    owner, editor, child = two_users_with_child(client, role="editor")
    resp = client.put(
        f"/api/children/{child['id']}/caregivers/{editor['id']}", json={"role": "owner"}, headers=auth_headers(owner["token"])
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# 18. Manipulasi membership lintas-anak ditolak (IDOR).
# --------------------------------------------------------------------------


def test_cross_child_membership_manipulation_is_rejected(client):
    owner_a = register(client, name="OA", email="oa@example.com")
    child_a = create_child(client, owner_a["token"], name="Anak A")
    owner_b = register(client, name="OB", email="ob@example.com")
    child_b = create_child(client, owner_b["token"], name="Anak B")

    caregiver_b = register(client, name="CB", email="cb@example.com")
    invite_and_join(client, owner_b["token"], child_b["id"], caregiver_b["token"], "editor")

    # owner_a nyoba ubah/cabut caregiver_b yang sebenernya milik child_b,
    # lewat URL child_a — HARUS ditolak (caregiver_b bukan member child_a)
    resp = client.put(
        f"/api/children/{child_a['id']}/caregivers/{caregiver_b['id']}",
        json={"role": "viewer"},
        headers=auth_headers(owner_a["token"]),
    )
    assert resp.status_code == 404

    resp2 = client.delete(
        f"/api/children/{child_a['id']}/caregivers/{caregiver_b['id']}", headers=auth_headers(owner_a["token"])
    )
    assert resp2.status_code == 404

    # membership caregiver_b di child_b TETAP utuh
    cc = ChildCaregiver.query.filter_by(child_id=child_b["id"], user_id=caregiver_b["id"]).first()
    assert cc is not None and cc.role == "editor"


# --------------------------------------------------------------------------
# 19-20. Revoke / demote langsung menghilangkan akses.
# --------------------------------------------------------------------------


def test_removed_caregiver_loses_read_and_write_access(client):
    owner, editor, child = two_users_with_child(client, role="editor")
    resp = client.delete(f"/api/children/{child['id']}/caregivers/{editor['id']}", headers=auth_headers(owner["token"]))
    assert resp.status_code == 200

    read_resp = client.get(f"/api/children/{child['id']}", headers=auth_headers(editor["token"]))
    assert read_resp.status_code == 404

    write_resp = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json={"feed_type": "asi_langsung"},
        headers={**auth_headers(editor["token"]), "X-Idempotency-Key": "after-revoke"},
    )
    assert write_resp.status_code == 404


def test_editor_changed_to_viewer_immediately_loses_write_access(client):
    owner, editor, child = two_users_with_child(client, role="editor")
    resp = client.put(
        f"/api/children/{child['id']}/caregivers/{editor['id']}", json={"role": "viewer"}, headers=auth_headers(owner["token"])
    )
    assert resp.status_code == 200
    assert resp.get_json()["role"] == "viewer"

    write_resp = client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json={"feed_type": "asi_langsung"},
        headers={**auth_headers(editor["token"]), "X-Idempotency-Key": "after-demote"},
    )
    assert write_resp.status_code == 403
    # tapi baca TETAP boleh (viewer)
    read_resp = client.get(f"/api/children/{child['id']}", headers=auth_headers(editor["token"]))
    assert read_resp.status_code == 200
    assert read_resp.get_json()["role"] == "viewer"


# --------------------------------------------------------------------------
# 21-22. Replay antrian offline/idempotent di-otorisasi ULANG tiap request;
# tulisan yang ditolak nggak nyimpen data ataupun audit event.
# --------------------------------------------------------------------------


def test_queued_idempotent_replay_is_reauthorized_after_demotion(client):
    """
    Simulasi antrian offline: editor bikin request PERTAMA (sukses,
    idempotency key tersimpan), lalu DITURUNKAN ke viewer SEBELUM request
    ke-2 (replay dengan key SAMA, kayak yang bakal dikirim ulang
    useOfflineSync.js kalau requestnya kepending pas offline). Replay
    HARUS ditolak backend — bukan diam-diam dianggap sukses (idempotency)
    ATAUPUN diam-diam ke-skip.
    """
    owner, editor, child = two_users_with_child(client, role="editor")
    headers = {**auth_headers(editor["token"]), "X-Idempotency-Key": "queued-key-1"}
    payload = {"feed_type": "asi_langsung", "duration_minutes": 5}

    r1 = client.post(f"/api/children/{child['id']}/feeding-logs", json=payload, headers=headers)
    assert r1.status_code == 201

    demote = client.put(
        f"/api/children/{child['id']}/caregivers/{editor['id']}", json={"role": "viewer"}, headers=auth_headers(owner["token"])
    )
    assert demote.status_code == 200

    r2 = client.post(f"/api/children/{child['id']}/feeding-logs", json=payload, headers=headers)
    assert r2.status_code == 403

    assert FeedingLog.query.filter_by(child_id=child["id"]).count() == 1  # bukan 0 (replay pertama tetap ada), bukan 2 (nggak dobel)


def test_rejected_write_produces_no_record_and_no_audit_event(client):
    owner, viewer, child = two_users_with_child(client, role="viewer")
    resp = client.post(
        f"/api/children/{child['id']}/mood-logs", json={"mood": "ceria"}, headers=auth_headers(viewer["token"])
    )
    assert resp.status_code == 403

    from models import MoodLog

    assert MoodLog.query.filter_by(child_id=child["id"]).count() == 0
    events = _list_events(client, owner["token"], child["id"]).get_json()["events"]
    assert [e for e in events if e["entity_type"] == "mood_log"] == []


# --------------------------------------------------------------------------
# 23-24. Mutasi membership (undang/ubah peran/cabut) menghasilkan TEPAT 1
# audit event privacy-safe; mutasi yang gagal nggak menghasilkan apa pun.
# --------------------------------------------------------------------------


def test_invite_produces_exactly_one_privacy_safe_membership_audit_event(client):
    owner = register(client, name="OwnerInv", email="owner-inv@example.com")
    child = create_child(client, owner["token"])
    resp = invite(client, owner["token"], child["id"], "editor")
    assert resp.status_code == 201

    events = _list_events(client, owner["token"], child["id"]).get_json()["events"]
    membership_events = [e for e in events if e["entity_type"] == "caregiver_membership"]
    assert len(membership_events) == 1
    ev = membership_events[0]
    assert ev["action"] == "create"
    assert ev["actor_user_id"] == owner["id"]
    assert ev["changed_fields"] == []

    payload_text = str(events)
    assert resp.get_json()["code"] not in payload_text  # token undangan TIDAK PERNAH masuk audit trail
    assert "owner-inv@example.com" not in payload_text


def test_role_change_produces_exactly_one_privacy_safe_membership_audit_event(client):
    owner, editor, child = two_users_with_child(client, role="editor")
    resp = client.put(
        f"/api/children/{child['id']}/caregivers/{editor['id']}", json={"role": "viewer"}, headers=auth_headers(owner["token"])
    )
    assert resp.status_code == 200

    events = _list_events(client, owner["token"], child["id"]).get_json()["events"]
    update_membership_events = [e for e in events if e["entity_type"] == "caregiver_membership" and e["action"] == "update"]
    assert len(update_membership_events) == 1
    assert update_membership_events[0]["changed_fields"] == []  # TIDAK PERNAH nyimpen peran lama/baru

    payload_text = str(events)
    assert "viewer" not in payload_text.lower()
    assert "editor" not in payload_text.lower()


def test_revoke_produces_exactly_one_privacy_safe_membership_audit_event(client):
    owner, editor, child = two_users_with_child(client, role="editor")
    resp = client.delete(f"/api/children/{child['id']}/caregivers/{editor['id']}", headers=auth_headers(owner["token"]))
    assert resp.status_code == 200

    events = _list_events(client, owner["token"], child["id"]).get_json()["events"]
    delete_membership_events = [e for e in events if e["entity_type"] == "caregiver_membership" and e["action"] == "delete"]
    assert len(delete_membership_events) == 1
    assert delete_membership_events[0]["changed_fields"] == []


def test_noop_role_change_produces_no_audit_event(client):
    owner, editor, child = two_users_with_child(client, role="editor")
    resp = client.put(
        f"/api/children/{child['id']}/caregivers/{editor['id']}", json={"role": "editor"}, headers=auth_headers(owner["token"])
    )
    assert resp.status_code == 200

    events = _list_events(client, owner["token"], child["id"]).get_json()["events"]
    update_membership_events = [e for e in events if e["entity_type"] == "caregiver_membership" and e["action"] == "update"]
    assert update_membership_events == []


def test_failed_membership_mutation_produces_no_audit_event(client):
    owner, editor, child = two_users_with_child(client, role="editor")
    # two_users_with_child() sendiri udah bikin 1 event "create" (undangan)
    # lewat setup-nya — baseline-nya dicatat DULU di sini, biar assert di
    # bawah murni ngecek TIDAK ADA event BARU yang nambah gara-gara role
    # change yang gagal ini (bukan "nol event sama sekali").
    before = _list_events(client, owner["token"], child["id"]).get_json()["events"]
    before_membership_count = len([e for e in before if e["entity_type"] == "caregiver_membership"])

    # role tidak valid -> 400, ditolak SEBELUM mutasi/audit apa pun
    resp = client.put(
        f"/api/children/{child['id']}/caregivers/{editor['id']}", json={"role": "owner"}, headers=auth_headers(owner["token"])
    )
    assert resp.status_code == 400

    after = _list_events(client, owner["token"], child["id"]).get_json()["events"]
    after_membership_count = len([e for e in after if e["entity_type"] == "caregiver_membership"])
    assert after_membership_count == before_membership_count


# --------------------------------------------------------------------------
# Issue 2 (review) — GET /children/<id>/caregivers TIDAK PERNAH bocorin
# email (atau field privat lain) ke editor/viewer. Lihat
# backend/docs/ROLES_PERMISSIONS.md bagian "Kontrak privasi
# GET /children/<id>/caregivers".
# --------------------------------------------------------------------------


FORBIDDEN_PRIVATE_TERMS = ["email", "@", "chat_id", "telegram", "password", "invite", "code", "token"]


def _list_caregivers(client, token, child_id):
    return client.get(f"/api/children/{child_id}/caregivers", headers=auth_headers(token))


def test_owner_can_list_caregivers(client):
    owner, editor, child = two_users_with_child(client, role="editor")
    resp = _list_caregivers(client, owner["token"], child["id"])
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) == 2
    editor_row = next(r for r in rows if r["role"] == "editor")
    assert editor_row["email"] == "caregiver-rp@example.com"  # owner beneran butuh ini


def test_editor_can_list_minimal_caregiver_information(client):
    owner, editor, child = two_users_with_child(client, role="editor")
    resp = _list_caregivers(client, editor["token"], child["id"])
    assert resp.status_code == 200
    for row in resp.get_json():
        assert set(row.keys()) == {"user_id", "name", "role"}


def test_viewer_can_list_the_same_privacy_minimal_information(client):
    owner, viewer, child = two_users_with_child(client, role="viewer")
    resp = _list_caregivers(client, viewer["token"], child["id"])
    assert resp.status_code == 200
    for row in resp.get_json():
        assert set(row.keys()) == {"user_id", "name", "role"}


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_editor_and_viewer_responses_never_contain_an_email_address(client, role):
    owner, member, child = two_users_with_child(client, role=role)
    resp = _list_caregivers(client, member["token"], child["id"])
    payload_text = resp.get_data(as_text=True)
    assert "@" not in payload_text
    assert "owner-rp@example.com" not in payload_text
    assert "caregiver-rp@example.com" not in payload_text


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_editor_and_viewer_responses_contain_no_unrelated_private_account_fields(client, role):
    owner, member, child = two_users_with_child(client, role=role)
    resp = _list_caregivers(client, member["token"], child["id"])
    payload_text = resp.get_data(as_text=True).lower()
    for term in FORBIDDEN_PRIVATE_TERMS:
        assert term not in payload_text, f"{term!r} bocor di respons caregiver-list buat role {role}"


def test_only_owner_receives_email_in_the_caregiver_list(client):
    owner, editor, child = two_users_with_child(client, role="editor")

    owner_rows = _list_caregivers(client, owner["token"], child["id"]).get_json()
    assert all("email" in r for r in owner_rows)

    editor_rows = _list_caregivers(client, editor["token"], child["id"]).get_json()
    assert all("email" not in r for r in editor_rows)


def test_user_without_child_access_cannot_list_caregivers(client):
    owner = register(client, name="OwnerC2", email="ownerc2@example.com")
    child = create_child(client, owner["token"])
    outsider = register(client, name="Outsider", email="outsider-c2@example.com")

    resp = _list_caregivers(client, outsider["token"], child["id"])
    assert resp.status_code == 404


def test_cross_child_access_is_rejected_without_revealing_private_membership_data(client):
    owner_a = register(client, name="OA2", email="oa2@example.com")
    child_a = create_child(client, owner_a["token"], name="Anak A2")
    owner_b = register(client, name="OB2", email="ob2@example.com")
    child_b = create_child(client, owner_b["token"], name="Anak B2")

    resp = _list_caregivers(client, owner_a["token"], child_b["id"])
    assert resp.status_code == 404
    assert "ob2@example.com" not in resp.get_data(as_text=True)


def test_existing_audit_filters_by_caregiver_still_work_with_privacy_minimal_list(client):
    """
    utils/roles.js:AuditTrailScreen cuma butuh user_id/name/role buat
    filter aktor — bukti endpoint list_caregivers yang sekarang
    privacy-minimal (buat non-owner) TETAP ngasih cukup info buat itu.
    """
    owner, editor, child = two_users_with_child(client, role="editor")
    _create(client, editor["token"], child["id"], "feeding_log", idem_key="k1")

    rows = _list_caregivers(client, editor["token"], child["id"]).get_json()
    editor_row = next(r for r in rows if r["role"] == "editor")
    assert editor_row["user_id"] == editor["id"]
    assert editor_row["name"] == "Pengasuh"

    events = _list_events(client, owner["token"], child["id"], actor_user_id=str(editor_row["user_id"])).get_json()["events"]
    assert len(events) == 1
    assert events[0]["actor_user_id"] == editor["id"]
