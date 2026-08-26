"""
Test Medication Schedule & Adherence — Phase 1
(`/children/<id>/medication-schedules` dkk). Lihat
backend/docs/MEDICATION_SCHEDULE.md buat kontrak lengkapnya.

SEMUA test pakai fixture `client` (SQLite in-memory), TIDAK PERNAH
menyentuh instance/tracker.db asli. "Sekarang" WAJIB dibekukan lewat
`_freeze_now()` (monkeypatch `routes.medication_schedule_routes.now_wib`)
di SETIAP test yang bergantung ke waktu/tanggal -- pola SAMA PERSIS
tests/test_reminders.py.
"""
import json
from datetime import datetime, timedelta

import pytest

import routes.medication_schedule_routes as medication_schedule_routes_module
from models import CaregiverAuditEvent, IdempotencyKey, MedicationDoseAction, MedicationLog, MedicationSchedule
from tests.conftest import auth_headers, create_child, register
from tests.test_roles_permissions import invite_and_join
from utils.medication_schedule_engine import LOOKBACK_DAYS, MAX_TIMES_PER_DAY

# Minggu, 10:00 WIB -- sama dengan FAKE_NOW di test_reminders.py, dipilih
# sembarang, cuma perlu tetap/deterministik.
FAKE_NOW = datetime(2026, 8, 23, 10, 0, 0)


def _freeze_now(monkeypatch, now=FAKE_NOW):
    monkeypatch.setattr(medication_schedule_routes_module, "now_wib", lambda: now)


def _list_schedules(client, token, child_id):
    return client.get(f"/api/children/{child_id}/medication-schedules", headers=auth_headers(token))


def _create_schedule(client, token, child_id, **overrides):
    payload = {
        "medication_name": "Paracetamol",
        "dose_value": 5,
        "dose_unit": "ml",
        "times_of_day": ["08:00"],
        "start_date": FAKE_NOW.date().isoformat(),
    }
    payload.update(overrides)
    return client.post(f"/api/children/{child_id}/medication-schedules", json=payload, headers=auth_headers(token))


def _patch_schedule(client, token, child_id, schedule_id, payload):
    return client.patch(f"/api/children/{child_id}/medication-schedules/{schedule_id}", json=payload, headers=auth_headers(token))


def _delete_schedule(client, token, child_id, schedule_id):
    return client.delete(f"/api/children/{child_id}/medication-schedules/{schedule_id}", headers=auth_headers(token))


def _act(client, token, child_id, schedule_id, occurrence_key, action, idem_key=None):
    headers = auth_headers(token)
    if idem_key:
        headers = {**headers, "X-Idempotency-Key": idem_key}
    return client.post(
        f"/api/children/{child_id}/medication-schedules/{schedule_id}/occurrences/{occurrence_key}/{action}",
        json={}, headers=headers,
    )


def _adherence(client, token, child_id, period="7d"):
    return client.get(
        f"/api/children/{child_id}/medication-schedules/adherence?period={period}", headers=auth_headers(token),
    )


def _occ_key(d, hhmm):
    return f"{d.isoformat()}T{hhmm}"


# --------------------------------------------------------------------------
# 1. Otorisasi: owner/editor/viewer, lintas anak, lintas user.
# --------------------------------------------------------------------------


def test_owner_can_list_create_edit_delete_and_act(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    resp = _create_schedule(client, user["token"], child["id"])
    assert resp.status_code == 201, resp.get_json()
    schedule_id = resp.get_json()["id"]

    listing = _list_schedules(client, user["token"], child["id"])
    assert listing.status_code == 200
    s = listing.get_json()["schedules"][0]
    assert s["can_edit"] is True and s["can_delete"] is True and s["can_act"] is True

    edit_resp = _patch_schedule(client, user["token"], child["id"], schedule_id, {"instructions": "Sebelum makan"})
    assert edit_resp.status_code == 200
    assert edit_resp.get_json()["instructions"] == "Sebelum makan"

    occ_key = _occ_key(FAKE_NOW.date(), "08:00")
    act_resp = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer")
    assert act_resp.status_code == 201, act_resp.get_json()

    del_resp = _delete_schedule(client, user["token"], child["id"], schedule_id)
    assert del_resp.status_code == 200


def test_editor_can_create_and_act_but_only_edit_delete_own_schedule(client, monkeypatch):
    _freeze_now(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-med@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-med@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")

    own_resp = _create_schedule(client, editor["token"], child["id"], medication_name="Obat Editor")
    assert own_resp.status_code == 201
    own_id = own_resp.get_json()["id"]
    assert _patch_schedule(client, editor["token"], child["id"], own_id, {"instructions": "x"}).status_code == 200

    owner_resp = _create_schedule(client, owner["token"], child["id"], medication_name="Obat Owner", times_of_day=["09:00"])
    owner_schedule_id = owner_resp.get_json()["id"]
    forbidden_edit = _patch_schedule(client, editor["token"], child["id"], owner_schedule_id, {"instructions": "coba"})
    assert forbidden_edit.status_code == 403
    forbidden_delete = _delete_schedule(client, editor["token"], child["id"], owner_schedule_id)
    assert forbidden_delete.status_code == 403

    # Editor TETAP boleh administer/skip okurensi milik OWNER (requirement:
    # administer/skip tidak dibatasi kepemilikan, beda dari edit/delete).
    occ_key = _occ_key(FAKE_NOW.date(), "09:00")
    act_resp = _act(client, editor["token"], child["id"], owner_schedule_id, occ_key, "administer")
    assert act_resp.status_code == 201, act_resp.get_json()


def test_viewer_can_only_view_never_mutate(client, monkeypatch):
    _freeze_now(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-med2@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-med@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")

    owner_resp = _create_schedule(client, owner["token"], child["id"])
    schedule_id = owner_resp.get_json()["id"]

    listing = _list_schedules(client, viewer["token"], child["id"])
    assert listing.status_code == 200
    s = listing.get_json()["schedules"][0]
    assert s["can_edit"] is False
    assert s["can_delete"] is False
    assert s["can_act"] is False

    assert _create_schedule(client, viewer["token"], child["id"]).status_code == 403
    assert _patch_schedule(client, viewer["token"], child["id"], schedule_id, {"instructions": "x"}).status_code == 403
    assert _delete_schedule(client, viewer["token"], child["id"], schedule_id).status_code == 403
    occ_key = _occ_key(FAKE_NOW.date(), "08:00")
    assert _act(client, viewer["token"], child["id"], schedule_id, occ_key, "administer").status_code == 403
    # Viewer TETAP boleh baca ringkasan kepatuhan.
    assert _adherence(client, viewer["token"], child["id"]).status_code == 200


def test_outsider_gets_404_not_403(client, monkeypatch):
    _freeze_now(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-med3@example.com")
    child = create_child(client, owner["token"])
    outsider = register(client, name="Orang Lain", email="outsider-med@example.com")

    assert _list_schedules(client, outsider["token"], child["id"]).status_code == 404
    assert _create_schedule(client, outsider["token"], child["id"]).status_code == 404


def test_unauthenticated_request_gets_401_not_404(client, monkeypatch):
    _freeze_now(monkeypatch)
    resp = client.get("/api/children/1/medication-schedules")
    assert resp.status_code == 401


def test_schedule_from_another_child_returns_404_not_leaked(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child_a = create_child(client, user["token"], name="Anak A")
    child_b = create_child(client, user["token"], name="Anak B")

    resp = _create_schedule(client, user["token"], child_a["id"])
    schedule_id = resp.get_json()["id"]

    assert _patch_schedule(client, user["token"], child_b["id"], schedule_id, {"instructions": "x"}).status_code == 404
    assert _delete_schedule(client, user["token"], child_b["id"], schedule_id).status_code == 404


# --------------------------------------------------------------------------
# 2. Validasi create/update.
# --------------------------------------------------------------------------


def test_create_rejects_empty_medication_name(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_schedule(client, user["token"], child["id"], medication_name="")
    assert resp.status_code == 400


def test_create_rejects_medication_name_over_max_length(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_schedule(client, user["token"], child["id"], medication_name="x" * 200)
    assert resp.status_code == 400


def test_create_rejects_dose_value_without_unit(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_schedule(client, user["token"], child["id"], dose_value=5, dose_unit=None)
    assert resp.status_code == 400


def test_create_rejects_dose_unit_without_value(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_schedule(client, user["token"], child["id"], dose_value=None, dose_unit="ml")
    assert resp.status_code == 400


def test_create_rejects_non_positive_dose_value(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_schedule(client, user["token"], child["id"], dose_value=0, dose_unit="ml")
    assert resp.status_code == 400


def test_create_rejects_invalid_dose_unit(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_schedule(client, user["token"], child["id"], dose_value=5, dose_unit="liter")
    assert resp.status_code == 400


def test_create_allows_omitting_dose_entirely(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_schedule(client, user["token"], child["id"], dose_value=None, dose_unit=None)
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["dose_value"] is None
    assert resp.get_json()["dose_unit"] is None


def test_create_rejects_empty_times_of_day(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_schedule(client, user["token"], child["id"], times_of_day=[])
    assert resp.status_code == 400


def test_create_rejects_invalid_time_format(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_schedule(client, user["token"], child["id"], times_of_day=["8:00"])
    assert resp.status_code == 400


def test_create_rejects_too_many_times_per_day(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    times = [f"{h:02d}:00" for h in range(MAX_TIMES_PER_DAY + 1)]
    resp = _create_schedule(client, user["token"], child["id"], times_of_day=times)
    assert resp.status_code == 400


def test_create_normalizes_duplicate_and_unsorted_times(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_schedule(client, user["token"], child["id"], times_of_day=["20:00", "08:00", "08:00"])
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["times_of_day"] == ["08:00", "20:00"]


def test_create_rejects_end_date_before_start_date(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_schedule(
        client, user["token"], child["id"],
        start_date=FAKE_NOW.date().isoformat(),
        end_date=(FAKE_NOW.date() - timedelta(days=1)).isoformat(),
    )
    assert resp.status_code == 400


def test_create_rejects_missing_start_date(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.post(
        f"/api/children/{child['id']}/medication-schedules",
        json={"medication_name": "Obat", "times_of_day": ["08:00"]},
        headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 400


def test_create_rejects_malformed_start_date(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_schedule(client, user["token"], child["id"], start_date="bukan-tanggal")
    assert resp.status_code == 400


def test_update_rejects_invalid_dose_unit(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]
    resp = _patch_schedule(client, user["token"], child["id"], schedule_id, {"dose_value": 1, "dose_unit": "liter"})
    assert resp.status_code == 400


def test_update_end_date_checked_against_existing_start_date(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"], start_date=FAKE_NOW.date().isoformat()).get_json()["id"]
    resp = _patch_schedule(client, user["token"], child["id"], schedule_id, {"end_date": (FAKE_NOW.date() - timedelta(days=10)).isoformat()})
    assert resp.status_code == 400


def test_delete_removes_schedule_and_its_actions(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]
    occ_key = _occ_key(FAKE_NOW.date(), "08:00")
    _act(client, user["token"], child["id"], schedule_id, occ_key, "administer")

    assert _delete_schedule(client, user["token"], child["id"], schedule_id).status_code == 200
    assert MedicationSchedule.query.get(schedule_id) is None
    assert MedicationDoseAction.query.filter_by(schedule_id=schedule_id).count() == 0


# --------------------------------------------------------------------------
# 3. Beberapa jam pemberian per hari.
# --------------------------------------------------------------------------


def test_multiple_daily_times_produce_multiple_occurrences_today(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    _create_schedule(client, user["token"], child["id"], times_of_day=["06:00", "14:00", "22:00"])

    body = _list_schedules(client, user["token"], child["id"]).get_json()
    occs = body["schedules"][0]["occurrences"]
    keys = sorted(o["occurrence_key"] for o in occs)
    today = FAKE_NOW.date().isoformat()
    assert keys == [f"{today}T06:00", f"{today}T14:00", f"{today}T22:00"]


def test_administering_one_time_does_not_affect_other_times_same_day(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"], times_of_day=["06:00", "14:00"]).get_json()["id"]

    occ_key_morning = _occ_key(FAKE_NOW.date(), "06:00")
    _act(client, user["token"], child["id"], schedule_id, occ_key_morning, "administer")

    body = _list_schedules(client, user["token"], child["id"]).get_json()
    occs = {o["occurrence_key"]: o for o in body["schedules"][0]["occurrences"]}
    today = FAKE_NOW.date().isoformat()
    assert occs[f"{today}T06:00"]["status"] == "administered"
    assert occs[f"{today}T14:00"]["status"] is None


# --------------------------------------------------------------------------
# 4. Batas tanggal mulai/selesai.
# --------------------------------------------------------------------------


def test_schedule_starting_in_future_produces_no_occurrences(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    start = FAKE_NOW.date() + timedelta(days=5)
    resp = _create_schedule(client, user["token"], child["id"], start_date=start.isoformat())
    assert resp.status_code == 201

    body = _list_schedules(client, user["token"], child["id"]).get_json()
    s = body["schedules"][0]
    assert s["occurrences"] == []
    assert s["next_occurrence_at"] is not None


def test_schedule_with_past_end_date_stops_generating_occurrences_after_it(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    start = FAKE_NOW.date() - timedelta(days=10)
    end = FAKE_NOW.date() - timedelta(days=3)
    _create_schedule(client, user["token"], child["id"], start_date=start.isoformat(), end_date=end.isoformat())

    body = _list_schedules(client, user["token"], child["id"]).get_json()
    occs = body["schedules"][0]["occurrences"]
    keys = sorted(o["occurrence_key"] for o in occs)
    assert keys[-1] == f"{end.isoformat()}T08:00"


def test_acting_on_future_start_date_schedule_is_rejected(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    start = FAKE_NOW.date() + timedelta(days=5)
    schedule_id = _create_schedule(client, user["token"], child["id"], start_date=start.isoformat()).get_json()["id"]

    occ_key = _occ_key(start, "08:00")
    resp = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer")
    assert resp.status_code == 400
    assert MedicationDoseAction.query.filter_by(schedule_id=schedule_id).count() == 0


# --------------------------------------------------------------------------
# 5. Ambang upcoming/due/overdue (reuse utils/reminder_engine.py).
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "minutes_since_scheduled,expected_state",
    [
        (-20, "upcoming"),
        (-15, "due"),
        (0, "due"),
        (30, "due"),
        (31, "overdue"),
    ],
)
def test_occurrence_state_thresholds(client, monkeypatch, minutes_since_scheduled, expected_state):
    """`minutes_since_scheduled` positif = okurensi di MASA LALU, negatif = di MASA DEPAN — pola sama dengan test_reminders.py."""
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    occ_time = FAKE_NOW - timedelta(minutes=minutes_since_scheduled)
    _create_schedule(
        client, user["token"], child["id"],
        times_of_day=[occ_time.strftime("%H:%M")], start_date=occ_time.date().isoformat(),
    )

    body = _list_schedules(client, user["token"], child["id"]).get_json()
    occ = body["schedules"][0]["occurrences"][0]
    assert occ["state"] == expected_state, (minutes_since_scheduled, body)


# --------------------------------------------------------------------------
# Defect 1 review (Agustus 2026): kebijakan actionability SAMA-HARI --
# okurensi yang MASIH "upcoming" (>15 menit lagi) TIDAK PERNAH boleh
# diaksi lebih awal, walau TANGGALNYA sendiri sudah sah hari ini. Lihat
# utils/medication_schedule_engine.py:is_occurrence_actionable().
# --------------------------------------------------------------------------


def test_same_day_occurrence_several_hours_in_the_future_is_rejected(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"], times_of_day=["08:00", "20:00"]).get_json()["id"]

    resp = _act(client, user["token"], child["id"], schedule_id, _occ_key(FAKE_NOW.date(), "20:00"), "administer")
    assert resp.status_code == 400
    assert "awal" in resp.get_json()["error"]


@pytest.mark.parametrize(
    "minutes_before_now,expected_status",
    [
        (16, 400),  # 16 menit lagi -- masih upcoming, ditolak
        (15, 201),  # TEPAT 15 menit lagi -- batas inklusif, diterima
        (0, 201),   # tepat waktu -- diterima
    ],
)
def test_administer_actionability_boundary(client, monkeypatch, minutes_before_now, expected_status):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    occ_time = FAKE_NOW + timedelta(minutes=minutes_before_now)
    schedule_id = _create_schedule(
        client, user["token"], child["id"],
        times_of_day=[occ_time.strftime("%H:%M")], start_date=occ_time.date().isoformat(),
    ).get_json()["id"]

    resp = _act(client, user["token"], child["id"], schedule_id, _occ_key(occ_time.date(), occ_time.strftime("%H:%M")), "administer")
    assert resp.status_code == expected_status, resp.get_json()


def test_overdue_occurrence_is_accepted(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    occ_time = FAKE_NOW - timedelta(hours=5)
    schedule_id = _create_schedule(
        client, user["token"], child["id"],
        times_of_day=[occ_time.strftime("%H:%M")], start_date=occ_time.date().isoformat(),
    ).get_json()["id"]

    resp = _act(client, user["token"], child["id"], schedule_id, _occ_key(occ_time.date(), occ_time.strftime("%H:%M")), "administer")
    assert resp.status_code == 201


def test_resolved_occurrence_has_can_act_false_in_list(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]
    occ_key = _occ_key(FAKE_NOW.date(), "08:00")
    assert _act(client, user["token"], child["id"], schedule_id, occ_key, "administer").status_code == 201

    body = _list_schedules(client, user["token"], child["id"]).get_json()
    occ = body["schedules"][0]["occurrences"][0]
    assert occ["status"] == "administered"
    assert occ["can_act"] is False


def test_too_early_occurrence_in_list_api_has_can_act_false(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    occ_time = FAKE_NOW + timedelta(minutes=16)
    _create_schedule(
        client, user["token"], child["id"],
        times_of_day=[occ_time.strftime("%H:%M")], start_date=FAKE_NOW.date().isoformat(),
    )

    body = _list_schedules(client, user["token"], child["id"]).get_json()
    occ = body["schedules"][0]["occurrences"][0]
    assert occ["state"] == "upcoming"
    assert occ["can_act"] is False


def test_exactly_at_boundary_occurrence_in_list_api_has_can_act_true(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    occ_time = FAKE_NOW + timedelta(minutes=15)
    _create_schedule(
        client, user["token"], child["id"],
        times_of_day=[occ_time.strftime("%H:%M")], start_date=FAKE_NOW.date().isoformat(),
    )

    body = _list_schedules(client, user["token"], child["id"]).get_json()
    occ = body["schedules"][0]["occurrences"][0]
    assert occ["state"] == "due"
    assert occ["can_act"] is True


def test_rejected_early_administer_creates_zero_medication_logs(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"], times_of_day=["20:00"]).get_json()["id"]

    resp = _act(client, user["token"], child["id"], schedule_id, _occ_key(FAKE_NOW.date(), "20:00"), "administer")
    assert resp.status_code == 400
    assert MedicationLog.query.filter_by(child_id=child["id"]).count() == 0


def test_rejected_early_administer_creates_zero_dose_actions(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"], times_of_day=["20:00"]).get_json()["id"]

    resp = _act(client, user["token"], child["id"], schedule_id, _occ_key(FAKE_NOW.date(), "20:00"), "administer")
    assert resp.status_code == 400
    assert MedicationDoseAction.query.filter_by(schedule_id=schedule_id).count() == 0


def test_rejected_early_administer_creates_zero_idempotency_rows_and_audit_events(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"], times_of_day=["20:00"]).get_json()["id"]

    resp = _act(client, user["token"], child["id"], schedule_id, _occ_key(FAKE_NOW.date(), "20:00"), "administer", idem_key="early-1")
    assert resp.status_code == 400
    assert IdempotencyKey.query.filter_by(user_id=user["id"], endpoint="medication-schedule-administer").count() == 0
    assert CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medication_dose_administered").count() == 0
    assert CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medication_log").count() == 0

    # Idempotency key nggak boleh "kepakai" -- retry pas okurensi udah
    # actionable TETAP dievaluasi ulang, bukan ke-replay dari respons
    # error yang gagal ini (pola sama persis test_reminders.py).
    _freeze_now(monkeypatch, now=FAKE_NOW + timedelta(hours=11))  # 20:00 hari yang sama -- sekarang due
    retry = _act(client, user["token"], child["id"], schedule_id, _occ_key(FAKE_NOW.date(), "20:00"), "administer", idem_key="early-1")
    assert retry.status_code == 201


def test_rejected_early_skip_creates_no_dose_action_or_audit_event(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"], times_of_day=["20:00"]).get_json()["id"]

    resp = _act(client, user["token"], child["id"], schedule_id, _occ_key(FAKE_NOW.date(), "20:00"), "skip")
    assert resp.status_code == 400
    assert MedicationDoseAction.query.filter_by(schedule_id=schedule_id).count() == 0
    assert CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medication_dose_skipped").count() == 0


def test_now_wib_is_sampled_exactly_once_per_action_request(client, monkeypatch):
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]

    calls = {"n": 0}

    def counting_now():
        calls["n"] += 1
        return FAKE_NOW

    monkeypatch.setattr(medication_schedule_routes_module, "now_wib", counting_now)
    resp = _act(client, user["token"], child["id"], schedule_id, _occ_key(FAKE_NOW.date(), "08:00"), "administer")
    assert resp.status_code == 201
    assert calls["n"] == 1


def test_offline_retry_after_occurrence_becomes_actionable_succeeds_exactly_once(client, monkeypatch):
    """
    Simulasi antrian offline: request PERTAMA dikirim saat okurensi
    MASIH terlalu awal (ditolak, TIDAK ADA idempotency key kesimpen) --
    "waktu" lalu maju sampai okurensi itu due, request DIULANG (retry
    antrian offline) dengan idempotency key yang SAMA -- HARUS diterima
    SEKALI, dan retry berikutnya lagi dengan key yang sama HARUS
    ke-replay (bukan bikin baris kedua).
    """
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"], times_of_day=["20:00"]).get_json()["id"]
    occ_key = _occ_key(FAKE_NOW.date(), "20:00")

    too_early = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer", idem_key="offline-retry-1")
    assert too_early.status_code == 400

    _freeze_now(monkeypatch, now=FAKE_NOW + timedelta(hours=10, minutes=5))  # 20:05 -- due
    synced = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer", idem_key="offline-retry-1")
    assert synced.status_code == 201
    assert MedicationDoseAction.query.filter_by(schedule_id=schedule_id).count() == 1

    replay = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer", idem_key="offline-retry-1")
    assert replay.status_code == 201
    assert replay.get_json()["id"] == synced.get_json()["id"]
    assert MedicationDoseAction.query.filter_by(schedule_id=schedule_id).count() == 1


def test_concurrent_conflict_protection_still_works_within_actionable_window(client, monkeypatch):
    """Regresi: penambahan cek actionability TIDAK PERNAH melemahkan sumbu konflik occurrence-sama/key-beda yang sudah ada."""
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]
    occ_key = _occ_key(FAKE_NOW.date(), "08:00")

    first = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer", idem_key="conflict-key-a")
    assert first.status_code == 201
    second = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer", idem_key="conflict-key-b")
    assert second.status_code == 409
    assert MedicationDoseAction.query.filter_by(schedule_id=schedule_id).count() == 1


# --------------------------------------------------------------------------
# 6. Jadwal nonaktif.
# --------------------------------------------------------------------------


def test_deactivating_a_schedule_hides_occurrences_and_clears_summary(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    overdue_time = FAKE_NOW - timedelta(hours=5)
    schedule_id = _create_schedule(
        client, user["token"], child["id"],
        times_of_day=[overdue_time.strftime("%H:%M")], start_date=overdue_time.date().isoformat(),
    ).get_json()["id"]

    before = _list_schedules(client, user["token"], child["id"]).get_json()
    assert before["summary"]["overdue_count"] == 1

    _patch_schedule(client, user["token"], child["id"], schedule_id, {"is_active": False})

    after = _list_schedules(client, user["token"], child["id"]).get_json()
    assert after["summary"]["overdue_count"] == 0
    deactivated = after["schedules"][0]
    assert deactivated["is_active"] is False
    assert deactivated["occurrences"] == []
    assert deactivated["next_occurrence_at"] is None


def test_cannot_act_on_an_inactive_schedule(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]
    _patch_schedule(client, user["token"], child["id"], schedule_id, {"is_active": False})

    occ_key = _occ_key(FAKE_NOW.date(), "08:00")
    resp = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer")
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# 7. Lookback dibatasi (nggak nggenerate nggak terbatas).
# --------------------------------------------------------------------------


def test_overdue_occurrences_are_bounded_by_lookback_window(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    start = FAKE_NOW.date() - timedelta(days=100)
    _create_schedule(client, user["token"], child["id"], start_date=start.isoformat())

    body = _list_schedules(client, user["token"], child["id"]).get_json()
    occs = body["schedules"][0]["occurrences"]
    assert len(occs) == LOOKBACK_DAYS + 1


def test_acting_far_outside_lookback_window_is_rejected(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    start = FAKE_NOW.date() - timedelta(days=100)
    schedule_id = _create_schedule(client, user["token"], child["id"], start_date=start.isoformat()).get_json()["id"]

    ancient_key = _occ_key(FAKE_NOW.date() - timedelta(days=99), "08:00")
    resp = _act(client, user["token"], child["id"], schedule_id, ancient_key, "administer")
    assert resp.status_code == 400


def test_acting_on_a_future_occurrence_key_is_rejected(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    start = FAKE_NOW.date() - timedelta(days=1)
    schedule_id = _create_schedule(client, user["token"], child["id"], start_date=start.isoformat()).get_json()["id"]

    future_key = _occ_key(FAKE_NOW.date() + timedelta(days=5), "08:00")
    resp = _act(client, user["token"], child["id"], schedule_id, future_key, "administer")
    assert resp.status_code == 400


def test_malformed_occurrence_key_is_rejected(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]

    resp = _act(client, user["token"], child["id"], schedule_id, "not-a-key", "administer")
    assert resp.status_code == 400


def test_occurrence_time_not_matching_times_of_day_is_rejected(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"], times_of_day=["08:00"]).get_json()["id"]

    wrong_time_key = _occ_key(FAKE_NOW.date(), "09:00")
    resp = _act(client, user["token"], child["id"], schedule_id, wrong_time_key, "administer")
    assert resp.status_code == 400
    assert MedicationDoseAction.query.filter_by(schedule_id=schedule_id).count() == 0


# --------------------------------------------------------------------------
# 8. Batas hari WIB.
# --------------------------------------------------------------------------


def test_asia_jakarta_day_boundary_is_used_for_occurrence_key(client, monkeypatch):
    """`now` dibekukan tepat 00:05 WIB tanggal 24 -- okurensi HARI INI harus 2026-08-24."""
    just_after_midnight_wib = datetime(2026, 8, 24, 0, 5, 0)
    _freeze_now(monkeypatch, just_after_midnight_wib)
    user = register(client)
    child = create_child(client, user["token"])
    start = datetime(2026, 8, 20).date()
    _create_schedule(client, user["token"], child["id"], start_date=start.isoformat(), times_of_day=["23:00"])

    body = _list_schedules(client, user["token"], child["id"]).get_json()
    keys = sorted(o["occurrence_key"] for o in body["schedules"][0]["occurrences"])
    assert keys[-1] == "2026-08-24T23:00"


# --------------------------------------------------------------------------
# 9-10. Idempotensi & konflik.
# --------------------------------------------------------------------------


def test_duplicate_administer_request_with_same_idempotency_key_replays_original(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]
    occ_key = _occ_key(FAKE_NOW.date(), "08:00")

    first = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer", idem_key="dup-key-1")
    second = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer", idem_key="dup-key-1")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.get_json()["id"] == second.get_json()["id"]
    assert MedicationDoseAction.query.filter_by(schedule_id=schedule_id).count() == 1
    assert MedicationLog.query.filter_by(child_id=child["id"]).count() == 1


def test_administering_an_already_resolved_occurrence_with_a_different_key_returns_409(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]
    occ_key = _occ_key(FAKE_NOW.date(), "08:00")

    first = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer", idem_key="key-a")
    assert first.status_code == 201
    second = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer", idem_key="key-b")
    assert second.status_code == 409
    assert MedicationDoseAction.query.filter_by(schedule_id=schedule_id).count() == 1
    assert MedicationLog.query.filter_by(child_id=child["id"]).count() == 1


def test_skip_after_administer_from_a_different_caregiver_is_a_409_not_an_overwrite(client, monkeypatch):
    _freeze_now(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-med4@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-med4@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")

    schedule_id = _create_schedule(client, owner["token"], child["id"]).get_json()["id"]
    occ_key = _occ_key(FAKE_NOW.date(), "08:00")

    administered = _act(client, owner["token"], child["id"], schedule_id, occ_key, "administer")
    assert administered.status_code == 201

    skip_attempt = _act(client, editor["token"], child["id"], schedule_id, occ_key, "skip")
    assert skip_attempt.status_code == 409

    action = MedicationDoseAction.query.filter_by(schedule_id=schedule_id).first()
    assert action.status == "administered"
    assert MedicationLog.query.filter_by(child_id=child["id"]).count() == 1


def test_idempotency_key_reused_with_different_occurrence_returns_conflict(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    # Kedua jam sengaja dipilih AKTIF (boleh diaksi) pada FAKE_NOW=10:00
    # -- "09:45" tepat di batas 15 menit due, bukan jam yang masih
    # upcoming, biar test ini murni nguji sumbu idempotency-key-beda-
    # occurrence, bukan ketimpa pengecekan kelayakan momen.
    schedule_id = _create_schedule(client, user["token"], child["id"], times_of_day=["08:00", "09:45"]).get_json()["id"]

    key1 = _occ_key(FAKE_NOW.date(), "08:00")
    key2 = _occ_key(FAKE_NOW.date(), "09:45")
    first = _act(client, user["token"], child["id"], schedule_id, key1, "administer", idem_key="shared-key")
    assert first.status_code == 201
    second = _act(client, user["token"], child["id"], schedule_id, key2, "administer", idem_key="shared-key")
    assert second.status_code == 409


# --------------------------------------------------------------------------
# 11. Administer bikin PERSIS 1 MedicationLog, skip nggak bikin apa-apa.
# --------------------------------------------------------------------------


def test_administer_creates_exactly_one_medication_log_with_correct_fields(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(
        client, user["token"], child["id"],
        medication_name="Amoxicillin", dose_value=2.5, dose_unit="ml",
    ).get_json()["id"]
    occ_key = _occ_key(FAKE_NOW.date(), "08:00")

    resp = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer")
    assert resp.status_code == 201
    action_body = resp.get_json()
    assert action_body["status"] == "administered"
    assert action_body["medication_log_id"] is not None

    logs = MedicationLog.query.filter_by(child_id=child["id"]).all()
    assert len(logs) == 1
    log = logs[0]
    assert log.id == action_body["medication_log_id"]
    assert log.medication_name == "Amoxicillin"
    assert log.dosage == "2.5 ml"
    assert log.created_by_user_id == user["id"]
    # `timestamp` log = waktu AKSI beneran (acted_at), BUKAN occurrence_at
    # terjadwal -- lihat requirement "preserve the distinction between
    # scheduled time and actual administration time".
    assert log.timestamp == FAKE_NOW


def test_skip_creates_no_medication_log(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]
    occ_key = _occ_key(FAKE_NOW.date(), "08:00")

    resp = _act(client, user["token"], child["id"], schedule_id, occ_key, "skip")
    assert resp.status_code == 201
    assert resp.get_json()["status"] == "skipped"
    assert resp.get_json()["medication_log_id"] is None
    assert MedicationLog.query.filter_by(child_id=child["id"]).count() == 0


def test_administer_transaction_rolls_back_entirely_if_log_creation_fails(client, monkeypatch):
    """
    Kegagalan bikin MedicationLog HARUS bikin SELURUH aksi batal (nggak ada
    MedicationDoseAction YATIM tanpa log-nya, nggak ada log SETENGAH jadi)
    -- disimulasikan dengan bikin konstruktor MedicationLog raise, jadi
    error kejadian SEBELUM baris aksi apa pun sempat dibikin.
    """
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]
    occ_key = _occ_key(FAKE_NOW.date(), "08:00")

    def boom(*args, **kwargs):
        raise RuntimeError("simulated medication log failure")

    monkeypatch.setattr(medication_schedule_routes_module, "MedicationLog", boom)

    # PROPAGATE_EXCEPTIONS=False (lihat app.py) -- exception nggak nembus
    # ke test_client(), tapi ketangkep global error handler dan jadi
    # respons 500 yang aman (lihat utils/observability.py). Invariant yang
    # beneran diuji TETAP SAMA: gagal bikin log -> TIDAK ADA aksi ATAUPUN
    # log yang kesimpen sama sekali, bukan cuma lognya doang.
    resp = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer")
    assert resp.status_code == 500

    assert MedicationDoseAction.query.filter_by(schedule_id=schedule_id).count() == 0
    assert MedicationLog.query.filter_by(child_id=child["id"]).count() == 0

    # Sesi berikutnya (request baru) tetap sehat -- teardown per-request
    # sudah membersihkan transaksi yang gagal ini.
    listing = _list_schedules(client, user["token"], child["id"])
    assert listing.status_code == 200


# --------------------------------------------------------------------------
# 12. Truth table kepatuhan.
# --------------------------------------------------------------------------


def test_adherence_percentage_is_none_when_no_expected_doses(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    start = FAKE_NOW.date() + timedelta(days=5)  # belum mulai -- 0 expected
    _create_schedule(client, user["token"], child["id"], start_date=start.isoformat())

    body = _adherence(client, user["token"], child["id"]).get_json()
    assert body["expected_count"] == 0
    assert body["adherence_percentage"] is None


def test_adherence_truth_table_administered_skipped_overdue_on_time_late(client, monkeypatch):
    """
    `now` dibekukan 10:00. `acted_at` SELALU `now_wib()` (10:00) --
    supaya "on time" beneran teruji, okurensi yang di-administer harus
    DEKAT 10:00 (bukan jauh di masa lalu, itu bakal "late").
    """
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    start = FAKE_NOW.date() - timedelta(days=1)
    schedule_id = _create_schedule(
        client, user["token"], child["id"], start_date=start.isoformat(),
        times_of_day=["06:00", "09:50", "14:00", "18:00"],
    ).get_json()["id"]

    today = FAKE_NOW.date()
    # Hari ini 09:50 -- administer ON TIME (10 menit sebelum "now"=10:00, <= 30 menit).
    _act(client, user["token"], child["id"], schedule_id, _occ_key(today, "09:50"), "administer")
    # Kemarin 06:00 -- skip.
    _act(client, user["token"], child["id"], schedule_id, _occ_key(start, "06:00"), "skip")
    # Kemarin 09:50/14:00/18:00 + hari ini 06:00 -- dibiarkan UNRESOLVED,
    # semuanya jauh > 30 menit dari "now" -- overdue.
    # Hari ini 14:00/18:00 -- MASA DEPAN relatif "now"=10:00, TIDAK PERNAH
    # masuk "expected" sama sekali.

    body = _adherence(client, user["token"], child["id"], period="7d").get_json()
    # Expected = okurensi yang occurrence_at <= now: kemarin (4 jam) +
    # hari ini 06:00 & 09:50 (2 jam) = 6 okurensi.
    assert body["expected_count"] == 6
    assert body["administered_count"] == 1
    assert body["skipped_count"] == 1
    assert body["on_time_administered_count"] == 1
    assert body["late_administered_count"] == 0
    assert body["overdue_unresolved_count"] == 4
    assert body["adherence_percentage"] == round(1 / 6 * 100, 1)


def test_adherence_late_administered_counted_separately_from_on_time(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    occ_time = FAKE_NOW - timedelta(hours=2)  # jauh sebelum sekarang
    schedule_id = _create_schedule(
        client, user["token"], child["id"],
        start_date=occ_time.date().isoformat(), times_of_day=[occ_time.strftime("%H:%M")],
    ).get_json()["id"]

    occ_key = _occ_key(occ_time.date(), occ_time.strftime("%H:%M"))
    # acted_at = FAKE_NOW (2 jam SETELAH occurrence_at) -- jauh di atas
    # DUE_AFTER_MINUTES=30, jadi HARUS "late", bukan "on_time".
    resp = _act(client, user["token"], child["id"], schedule_id, occ_key, "administer")
    assert resp.status_code == 201

    body = _adherence(client, user["token"], child["id"], period="7d").get_json()
    assert body["administered_count"] == 1
    assert body["late_administered_count"] == 1
    assert body["on_time_administered_count"] == 0


def test_adherence_rejects_unsupported_period(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _adherence(client, user["token"], child["id"], period="90d")
    assert resp.status_code == 400


def test_adherence_30d_includes_more_history_than_7d(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    start = FAKE_NOW.date() - timedelta(days=20)
    _create_schedule(client, user["token"], child["id"], start_date=start.isoformat())

    seven = _adherence(client, user["token"], child["id"], period="7d").get_json()
    thirty = _adherence(client, user["token"], child["id"], period="30d").get_json()
    assert thirty["expected_count"] > seven["expected_count"]


# --------------------------------------------------------------------------
# 13. Audit trail tanpa nilai sensitif.
# --------------------------------------------------------------------------


def test_create_schedule_produces_audit_event_without_sensitive_medication_name(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    sensitive_name = "RAHASIA_Amoxicillin_500mg"
    schedule_id = _create_schedule(client, user["token"], child["id"], medication_name=sensitive_name).get_json()["id"]

    event = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medication_schedule", action="create").first()
    assert event is not None
    assert event.entity_id == schedule_id
    body_text = json.dumps(event.to_dict())
    assert sensitive_name not in body_text
    assert "RAHASIA" not in body_text


def test_update_medication_name_only_records_private_marker_not_the_value(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]

    _patch_schedule(client, user["token"], child["id"], schedule_id, {"medication_name": "RAHASIA_Ibuprofen"})

    event = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medication_schedule", action="update").first()
    assert event is not None
    assert event.changed_fields_json == ["private_details"]
    assert "RAHASIA" not in json.dumps(event.to_dict())
    assert "Ibuprofen" not in json.dumps(event.to_dict())


def test_update_start_date_records_safe_field_name(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]

    new_start = (FAKE_NOW.date() - timedelta(days=1)).isoformat()
    _patch_schedule(client, user["token"], child["id"], schedule_id, {"start_date": new_start})

    event = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medication_schedule", action="update").first()
    assert event is not None
    assert event.changed_fields_json == ["start_date"]


def test_delete_schedule_produces_audit_event(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"]).get_json()["id"]

    _delete_schedule(client, user["token"], child["id"], schedule_id)

    event = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medication_schedule", action="delete").first()
    assert event is not None
    assert event.entity_id == schedule_id


def test_administer_and_skip_produce_distinct_audit_entity_types(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"], times_of_day=["06:00", "08:00"]).get_json()["id"]

    _act(client, user["token"], child["id"], schedule_id, _occ_key(FAKE_NOW.date(), "06:00"), "administer")
    _act(client, user["token"], child["id"], schedule_id, _occ_key(FAKE_NOW.date(), "08:00"), "skip")

    administered_events = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medication_dose_administered").all()
    skipped_events = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medication_dose_skipped").all()
    assert len(administered_events) == 1
    assert len(skipped_events) == 1
    assert administered_events[0].action == "create"
    assert skipped_events[0].action == "create"
    assert administered_events[0].changed_fields_json is None
    assert skipped_events[0].changed_fields_json is None


def test_administer_also_audits_the_auto_created_medication_log(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    schedule_id = _create_schedule(client, user["token"], child["id"], medication_name="RAHASIA_Obat").get_json()["id"]

    resp = _act(client, user["token"], child["id"], schedule_id, _occ_key(FAKE_NOW.date(), "08:00"), "administer")
    log_id = resp.get_json()["medication_log_id"]

    event = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medication_log", action="create").first()
    assert event is not None
    assert event.entity_id == log_id
    assert "RAHASIA" not in json.dumps(event.to_dict())


# --------------------------------------------------------------------------
# 14. Regresi endpoint lain yang sudah ada.
# --------------------------------------------------------------------------


def test_existing_stats_endpoint_still_works_after_medication_schedule_addition(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.get(f"/api/children/{child['id']}/stats?days=7", headers=auth_headers(user["token"]))
    assert resp.status_code == 200


def test_list_medication_schedules_does_not_crash_for_children_with_future_start_dates(client, monkeypatch):
    """
    Regresi: `valid_occurrence_range()` balikin `None` buat schedule yang
    `start_date`-nya sendiri di masa depan -- pemanggil di
    routes/medication_schedule_routes.py WAJIB nge-guard `None` ini sebelum
    unpacking, kalau kelupaan bakal 500, bukan cuma occurrence yang
    bermasalah.
    """
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    _create_schedule(client, user["token"], child["id"], start_date=(FAKE_NOW.date() + timedelta(days=1)).isoformat())
    _create_schedule(client, user["token"], child["id"], start_date=(FAKE_NOW.date() - timedelta(days=1)).isoformat())

    resp = _list_schedules(client, user["token"], child["id"])
    assert resp.status_code == 200
    assert len(resp.get_json()["schedules"]) == 2
