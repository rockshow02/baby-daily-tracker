"""
Test Care Reminders & Schedules — Phase 1 (`/children/<id>/reminders`
dkk). Lihat backend/docs/REMINDERS.md buat kontrak lengkapnya.

SEMUA test pakai fixture `client` (SQLite in-memory), TIDAK PERNAH
menyentuh instance/tracker.db asli. "Sekarang" WAJIB dibekukan lewat
`_freeze_now()` (monkeypatch `routes.reminder_routes.now_wib`) di SETIAP
test yang bergantung ke waktu/tanggal — endpoint ini SENGAJA manggil
`now_wib()` di layer route (bukan di utils/reminder_engine.py) justru
biar bisa dites deterministik, konsisten sama pola test_insights.py.
"""
import json
from datetime import datetime, timedelta

import pytest

import routes.reminder_routes as reminder_routes_module
from models import CaregiverAuditEvent, Reminder, ReminderAction
from tests.conftest import auth_headers, create_child, register
from tests.test_roles_permissions import invite_and_join
from utils.reminder_engine import DAILY_LOOKBACK_DAYS

# Minggu, 10:00 WIB -- dipilih sembarang, cuma perlu tetap/deterministik.
FAKE_NOW = datetime(2026, 8, 23, 10, 0, 0)


def _freeze_now(monkeypatch, now=FAKE_NOW):
    monkeypatch.setattr(reminder_routes_module, "now_wib", lambda: now)


def _list_reminders(client, token, child_id):
    return client.get(f"/api/children/{child_id}/reminders", headers=auth_headers(token))


def _create_reminder(client, token, child_id, **overrides):
    payload = {
        "reminder_type": "medication",
        "title": "Obat pagi",
        "scheduled_at": FAKE_NOW.isoformat(),
        "recurrence": "none",
    }
    payload.update(overrides)
    return client.post(f"/api/children/{child_id}/reminders", json=payload, headers=auth_headers(token))


def _patch_reminder(client, token, child_id, reminder_id, payload):
    return client.patch(f"/api/children/{child_id}/reminders/{reminder_id}", json=payload, headers=auth_headers(token))


def _delete_reminder(client, token, child_id, reminder_id):
    return client.delete(f"/api/children/{child_id}/reminders/{reminder_id}", headers=auth_headers(token))


def _act(client, token, child_id, reminder_id, occurrence_key, action, body=None, idem_key=None):
    headers = auth_headers(token)
    if idem_key:
        headers = {**headers, "X-Idempotency-Key": idem_key}
    return client.post(
        f"/api/children/{child_id}/reminders/{reminder_id}/occurrences/{occurrence_key}/{action}",
        json=body or {}, headers=headers,
    )


# --------------------------------------------------------------------------
# 1-2. Otorisasi: owner/editor/viewer, lintas anak, lintas user.
# --------------------------------------------------------------------------


def test_owner_can_list_create_edit_delete_and_act(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    resp = _create_reminder(client, user["token"], child["id"])
    assert resp.status_code == 201, resp.get_json()
    reminder_id = resp.get_json()["id"]

    listing = _list_reminders(client, user["token"], child["id"])
    assert listing.status_code == 200
    r = listing.get_json()["reminders"][0]
    assert r["can_edit"] is True and r["can_delete"] is True and r["can_act"] is True

    edit_resp = _patch_reminder(client, user["token"], child["id"], reminder_id, {"title": "Obat siang"})
    assert edit_resp.status_code == 200
    assert edit_resp.get_json()["title"] == "Obat siang"

    occ_key = FAKE_NOW.date().isoformat()
    act_resp = _act(client, user["token"], child["id"], reminder_id, occ_key, "complete")
    assert act_resp.status_code == 201, act_resp.get_json()

    del_resp = _delete_reminder(client, user["token"], child["id"], reminder_id)
    assert del_resp.status_code == 200


def test_editor_can_create_and_act_but_only_edit_delete_own_reminder(client, monkeypatch):
    _freeze_now(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-rem@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-rem@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")

    # editor bikin reminder sendiri -- boleh diedit/dihapus sendiri
    own_resp = _create_reminder(client, editor["token"], child["id"], title="Punya editor")
    assert own_resp.status_code == 201
    own_id = own_resp.get_json()["id"]
    assert _patch_reminder(client, editor["token"], child["id"], own_id, {"title": "Diubah editor"}).status_code == 200

    # owner bikin reminder -- editor TIDAK boleh edit/hapus punya owner
    owner_resp = _create_reminder(client, owner["token"], child["id"], title="Punya owner", scheduled_at=(FAKE_NOW + timedelta(hours=1)).isoformat())
    owner_reminder_id = owner_resp.get_json()["id"]
    forbidden_edit = _patch_reminder(client, editor["token"], child["id"], owner_reminder_id, {"title": "Coba diubah editor"})
    assert forbidden_edit.status_code == 403
    forbidden_delete = _delete_reminder(client, editor["token"], child["id"], owner_reminder_id)
    assert forbidden_delete.status_code == 403

    # TAPI editor TETAP boleh complete/skip occurrence reminder OWNER
    # (requirement: "Complete or skip reminders" nggak dibatasi ownership,
    # beda dari edit/delete definisinya).
    occ_key = FAKE_NOW.date().isoformat()
    act_resp = _act(client, editor["token"], child["id"], owner_reminder_id, occ_key, "complete")
    assert act_resp.status_code == 201, act_resp.get_json()


def test_viewer_can_only_view_never_mutate(client, monkeypatch):
    _freeze_now(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-rem2@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-rem@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")

    owner_resp = _create_reminder(client, owner["token"], child["id"])
    reminder_id = owner_resp.get_json()["id"]

    assert _list_reminders(client, viewer["token"], child["id"]).status_code == 200
    listing = _list_reminders(client, viewer["token"], child["id"]).get_json()["reminders"][0]
    assert listing["can_edit"] is False
    assert listing["can_delete"] is False
    assert listing["can_act"] is False

    assert _create_reminder(client, viewer["token"], child["id"]).status_code == 403
    assert _patch_reminder(client, viewer["token"], child["id"], reminder_id, {"title": "x"}).status_code == 403
    assert _delete_reminder(client, viewer["token"], child["id"], reminder_id).status_code == 403
    occ_key = FAKE_NOW.date().isoformat()
    assert _act(client, viewer["token"], child["id"], reminder_id, occ_key, "complete").status_code == 403


def test_outsider_gets_404_not_403(client, monkeypatch):
    _freeze_now(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-rem3@example.com")
    child = create_child(client, owner["token"])
    outsider = register(client, name="Orang Lain", email="outsider-rem@example.com")

    assert _list_reminders(client, outsider["token"], child["id"]).status_code == 404
    assert _create_reminder(client, outsider["token"], child["id"]).status_code == 404


def test_unauthenticated_request_gets_401_not_404(client, monkeypatch):
    _freeze_now(monkeypatch)
    resp = client.get("/api/children/1/reminders")
    assert resp.status_code == 401


def test_reminder_from_another_child_returns_404_not_leaked(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child_a = create_child(client, user["token"], name="Anak A")
    child_b = create_child(client, user["token"], name="Anak B")

    resp = _create_reminder(client, user["token"], child_a["id"])
    reminder_id = resp.get_json()["id"]

    # reminder milik child_a, diakses lewat URL child_b -- HARUS 404, nggak
    # boleh ke-edit/ke-lihat lewat anak yang salah (cegah IDOR lintas anak).
    assert _patch_reminder(client, user["token"], child_b["id"], reminder_id, {"title": "x"}).status_code == 404
    assert _delete_reminder(client, user["token"], child_b["id"], reminder_id).status_code == 404


# --------------------------------------------------------------------------
# 3. Validasi create/update.
# --------------------------------------------------------------------------


def test_create_rejects_invalid_reminder_type(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_reminder(client, user["token"], child["id"], reminder_type="bukan_tipe_valid")
    assert resp.status_code == 400


def test_create_rejects_invalid_recurrence(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_reminder(client, user["token"], child["id"], recurrence="weekly")
    assert resp.status_code == 400


def test_create_rejects_empty_title(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_reminder(client, user["token"], child["id"], title="")
    assert resp.status_code == 400


def test_create_rejects_title_over_max_length(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _create_reminder(client, user["token"], child["id"], title="x" * 200)
    assert resp.status_code == 400


def test_create_rejects_missing_scheduled_at(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.post(
        f"/api/children/{child['id']}/reminders",
        json={"reminder_type": "medication", "title": "Obat"},
        headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 400


def test_update_rejects_invalid_recurrence(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"]).get_json()["id"]
    resp = _patch_reminder(client, user["token"], child["id"], reminder_id, {"recurrence": "monthly"})
    assert resp.status_code == 400


def test_delete_removes_reminder_and_its_actions(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"]).get_json()["id"]
    occ_key = FAKE_NOW.date().isoformat()
    _act(client, user["token"], child["id"], reminder_id, occ_key, "complete")

    assert _delete_reminder(client, user["token"], child["id"], reminder_id).status_code == 200
    assert Reminder.query.get(reminder_id) is None
    assert ReminderAction.query.filter_by(reminder_id=reminder_id).count() == 0


# --------------------------------------------------------------------------
# 4/7. Perhitungan status reminder sekali-jalan + ambang upcoming/due/overdue.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "minutes_since_scheduled,expected_state",
    [
        (-20, "upcoming"),  # jadwalnya 20 menit LAGI -> lebih dari 15 menit -> upcoming
        (-15, "due"),       # jadwalnya TEPAT 15 menit lagi -> due (batas inklusif)
        (0, "due"),         # tepat waktu -> due
        (30, "due"),        # 30 menit LEWAT dari jadwal -> masih due (batas inklusif)
        (31, "overdue"),    # 31 menit lewat -> overdue
    ],
)
def test_one_time_reminder_state_thresholds(client, monkeypatch, minutes_since_scheduled, expected_state):
    """`minutes_since_scheduled` positif = jadwalnya di MASA LALU (udah lewat sekian menit), negatif = jadwalnya di MASA DEPAN."""
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    scheduled_at = FAKE_NOW - timedelta(minutes=minutes_since_scheduled)
    _create_reminder(client, user["token"], child["id"], scheduled_at=scheduled_at.isoformat())

    body = _list_reminders(client, user["token"], child["id"]).get_json()
    occ = body["reminders"][0]["occurrences"][0]
    assert occ["state"] == expected_state, (minutes_since_scheduled, body)


def test_one_time_reminder_far_in_past_is_overdue(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    scheduled_at = FAKE_NOW - timedelta(hours=5)
    _create_reminder(client, user["token"], child["id"], scheduled_at=scheduled_at.isoformat())

    body = _list_reminders(client, user["token"], child["id"]).get_json()
    assert body["reminders"][0]["occurrences"][0]["state"] == "overdue"
    assert body["summary"]["overdue_count"] == 1


def test_one_time_reminder_far_in_future_is_upcoming(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    scheduled_at = FAKE_NOW + timedelta(days=3)
    _create_reminder(client, user["token"], child["id"], scheduled_at=scheduled_at.isoformat())

    body = _list_reminders(client, user["token"], child["id"]).get_json()
    assert body["reminders"][0]["occurrences"][0]["state"] == "upcoming"
    assert body["summary"]["due_count"] == 0
    assert body["summary"]["overdue_count"] == 0
    assert body["summary"]["next_upcoming_at"] is not None


# --------------------------------------------------------------------------
# 5-6. Rekurensi harian lintas hari + batas WIB.
# --------------------------------------------------------------------------


def test_daily_recurrence_shows_todays_occurrence(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    # reminder dibikin beberapa hari lalu, jam 08:00, harian
    started_at = datetime(2026, 8, 18, 8, 0, 0)
    _create_reminder(client, user["token"], child["id"], recurrence="daily", scheduled_at=started_at.isoformat())

    body = _list_reminders(client, user["token"], child["id"]).get_json()
    occs = body["reminders"][0]["occurrences"]
    today_key = FAKE_NOW.date().isoformat()
    todays = [o for o in occs if o["occurrence_key"] == today_key]
    assert len(todays) == 1
    # jam okurensi hari ini WAJIB ikut jam ASLI reminder (08:00), bukan jam
    # dibuatnya baris ini.
    assert todays[0]["occurrence_at"].startswith(f"{today_key}T08:00:00")


def test_daily_recurrence_shows_unresolved_past_days_as_overdue(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    started_at = datetime(2026, 8, 20, 8, 0, 0)  # 3 hari sebelum FAKE_NOW (08-23)
    _create_reminder(client, user["token"], child["id"], recurrence="daily", scheduled_at=started_at.isoformat())

    body = _list_reminders(client, user["token"], child["id"]).get_json()
    occs = body["reminders"][0]["occurrences"]
    keys = sorted(o["occurrence_key"] for o in occs)
    # 08-20, 08-21, 08-22 (overdue, belum diselesaikan) + 08-23 (hari ini)
    assert keys == ["2026-08-20", "2026-08-21", "2026-08-22", "2026-08-23"]
    for o in occs:
        if o["occurrence_key"] != "2026-08-23":
            assert o["state"] == "overdue"


def test_daily_recurrence_completing_one_day_does_not_affect_other_days(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    started_at = datetime(2026, 8, 21, 8, 0, 0)
    reminder_id = _create_reminder(client, user["token"], child["id"], recurrence="daily", scheduled_at=started_at.isoformat()).get_json()["id"]

    _act(client, user["token"], child["id"], reminder_id, "2026-08-22", "complete")

    body = _list_reminders(client, user["token"], child["id"]).get_json()
    occs = {o["occurrence_key"]: o for o in body["reminders"][0]["occurrences"]}
    assert occs["2026-08-22"]["state"] == "completed"
    assert occs["2026-08-21"]["state"] == "overdue"  # nggak ikut ke-resolve


def test_asia_jakarta_day_boundary_is_used_for_daily_occurrence_key(client, monkeypatch):
    """
    `now` dibekukan tepat 00:05 WIB tanggal 24 -- occurrence HARI INI
    harus 2026-08-24 (batas hari WIB, BUKAN mundur ke 23 kalau salah
    dihitung pakai UTC yang beda 7 jam).
    """
    just_after_midnight_wib = datetime(2026, 8, 24, 0, 5, 0)
    _freeze_now(monkeypatch, just_after_midnight_wib)
    user = register(client)
    child = create_child(client, user["token"])
    started_at = datetime(2026, 8, 20, 23, 0, 0)
    _create_reminder(client, user["token"], child["id"], recurrence="daily", scheduled_at=started_at.isoformat())

    body = _list_reminders(client, user["token"], child["id"]).get_json()
    keys = sorted(o["occurrence_key"] for o in body["reminders"][0]["occurrences"])
    assert keys[-1] == "2026-08-24"


# --------------------------------------------------------------------------
# 8. Persistensi completed/skipped.
# --------------------------------------------------------------------------


def test_completed_occurrence_persists_and_is_reflected_in_next_list(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"]).get_json()["id"]
    occ_key = FAKE_NOW.date().isoformat()

    resp = _act(client, user["token"], child["id"], reminder_id, occ_key, "complete")
    assert resp.status_code == 201
    assert resp.get_json()["status"] == "completed"

    body = _list_reminders(client, user["token"], child["id"]).get_json()
    occ = body["reminders"][0]["occurrences"][0]
    assert occ["status"] == "completed"
    assert occ["state"] == "completed"
    assert occ["acted_by_user_id"] == user["id"]


def test_skipped_occurrence_persists(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"]).get_json()["id"]
    occ_key = FAKE_NOW.date().isoformat()

    resp = _act(client, user["token"], child["id"], reminder_id, occ_key, "skip")
    assert resp.status_code == 201
    assert resp.get_json()["status"] == "skipped"

    body = _list_reminders(client, user["token"], child["id"]).get_json()
    assert body["reminders"][0]["occurrences"][0]["status"] == "skipped"


# --------------------------------------------------------------------------
# 9-11. Idempotensi & konflik.
# --------------------------------------------------------------------------


def test_duplicate_complete_request_with_same_idempotency_key_replays_original(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"]).get_json()["id"]
    occ_key = FAKE_NOW.date().isoformat()

    first = _act(client, user["token"], child["id"], reminder_id, occ_key, "complete", idem_key="dup-key-1")
    second = _act(client, user["token"], child["id"], reminder_id, occ_key, "complete", idem_key="dup-key-1")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.get_json()["id"] == second.get_json()["id"]
    assert ReminderAction.query.filter_by(reminder_id=reminder_id).count() == 1


def test_completing_an_already_completed_occurrence_with_a_different_key_returns_409(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"]).get_json()["id"]
    occ_key = FAKE_NOW.date().isoformat()

    first = _act(client, user["token"], child["id"], reminder_id, occ_key, "complete", idem_key="key-a")
    assert first.status_code == 201
    second = _act(client, user["token"], child["id"], reminder_id, occ_key, "complete", idem_key="key-b")
    assert second.status_code == 409
    assert ReminderAction.query.filter_by(reminder_id=reminder_id).count() == 1


def test_skip_after_complete_from_a_different_caregiver_is_a_409_not_an_overwrite(client, monkeypatch):
    """Occurrence yang UDAH completed nggak pernah bisa 'ketimpa' jadi skipped lewat retry/aksi lain — requirement anti-race."""
    _freeze_now(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-rem4@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-rem4@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")

    reminder_id = _create_reminder(client, owner["token"], child["id"]).get_json()["id"]
    occ_key = FAKE_NOW.date().isoformat()

    completed = _act(client, owner["token"], child["id"], reminder_id, occ_key, "complete")
    assert completed.status_code == 201

    skip_attempt = _act(client, editor["token"], child["id"], reminder_id, occ_key, "skip")
    assert skip_attempt.status_code == 409

    action = ReminderAction.query.filter_by(reminder_id=reminder_id).first()
    assert action.status == "completed"  # TETAP completed, nggak ketimpa


def test_idempotency_key_reused_with_different_occurrence_returns_conflict_not_stale_response(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    started_at = datetime(2026, 8, 21, 8, 0, 0)
    reminder_id = _create_reminder(client, user["token"], child["id"], recurrence="daily", scheduled_at=started_at.isoformat()).get_json()["id"]

    first = _act(client, user["token"], child["id"], reminder_id, "2026-08-22", "complete", idem_key="shared-key")
    assert first.status_code == 201
    # key SAMA, occurrence BEDA -- fingerprint nggak bakal cocok, harus 409, bukan diam-diam ngebalikin hasil "2026-08-22".
    second = _act(client, user["token"], child["id"], reminder_id, "2026-08-23", "complete", idem_key="shared-key")
    assert second.status_code == 409


# --------------------------------------------------------------------------
# 12. Okurensi overdue dibatasi (nggak nggenerate nggak terbatas).
# --------------------------------------------------------------------------


def test_daily_overdue_occurrences_are_bounded_by_lookback_window(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    # reminder udah aktif 100 hari, TAPI list nggak boleh nunjukin 100 baris overdue.
    started_at = FAKE_NOW - timedelta(days=100)
    _create_reminder(client, user["token"], child["id"], recurrence="daily", scheduled_at=started_at.isoformat())

    body = _list_reminders(client, user["token"], child["id"]).get_json()
    occs = body["reminders"][0]["occurrences"]
    # dibatasi DAILY_LOOKBACK_DAYS hari ke belakang + hari ini sendiri --
    # BUKAN 100 baris (1 per hari sejak reminder ini dibuat).
    assert len(occs) == DAILY_LOOKBACK_DAYS + 1


def test_acting_far_outside_lookback_window_is_rejected(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    started_at = FAKE_NOW - timedelta(days=100)
    reminder_id = _create_reminder(client, user["token"], child["id"], recurrence="daily", scheduled_at=started_at.isoformat()).get_json()["id"]

    ancient_key = (FAKE_NOW - timedelta(days=99)).date().isoformat()
    resp = _act(client, user["token"], child["id"], reminder_id, ancient_key, "complete")
    assert resp.status_code == 400


def test_acting_on_a_future_occurrence_is_rejected(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    started_at = FAKE_NOW - timedelta(days=1)
    reminder_id = _create_reminder(client, user["token"], child["id"], recurrence="daily", scheduled_at=started_at.isoformat()).get_json()["id"]

    future_key = (FAKE_NOW + timedelta(days=5)).date().isoformat()
    resp = _act(client, user["token"], child["id"], reminder_id, future_key, "complete")
    assert resp.status_code == 400


def test_malformed_occurrence_key_is_rejected(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"]).get_json()["id"]

    resp = _act(client, user["token"], child["id"], reminder_id, "not-a-date", "complete")
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# 13. Nonaktifkan reminder.
# --------------------------------------------------------------------------


def test_deactivating_a_reminder_hides_it_from_due_overdue_summary(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    scheduled_at = FAKE_NOW - timedelta(hours=5)  # overdue kalau aktif
    reminder_id = _create_reminder(client, user["token"], child["id"], scheduled_at=scheduled_at.isoformat()).get_json()["id"]

    before = _list_reminders(client, user["token"], child["id"]).get_json()
    assert before["summary"]["overdue_count"] == 1

    _patch_reminder(client, user["token"], child["id"], reminder_id, {"is_active": False})

    after = _list_reminders(client, user["token"], child["id"]).get_json()
    assert after["summary"]["overdue_count"] == 0
    deactivated = after["reminders"][0]
    assert deactivated["is_active"] is False
    assert deactivated["occurrences"] == []
    assert deactivated["next_occurrence_at"] is None


def test_cannot_act_on_an_inactive_reminder(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"]).get_json()["id"]
    _patch_reminder(client, user["token"], child["id"], reminder_id, {"is_active": False})

    occ_key = FAKE_NOW.date().isoformat()
    resp = _act(client, user["token"], child["id"], reminder_id, occ_key, "complete")
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# 14. Audit trail tanpa nilai sensitif.
# --------------------------------------------------------------------------


def test_create_reminder_produces_audit_event_without_sensitive_title(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    sensitive_title = "RAHASIA_Paracetamol_500mg"
    reminder_id = _create_reminder(client, user["token"], child["id"], title=sensitive_title).get_json()["id"]

    event = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="reminder", action="create").first()
    assert event is not None
    assert event.entity_id == reminder_id
    body_text = json.dumps(event.to_dict())
    assert sensitive_title not in body_text
    assert "RAHASIA" not in body_text


def test_update_reminder_title_only_records_private_marker_not_the_value(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"]).get_json()["id"]

    _patch_reminder(client, user["token"], child["id"], reminder_id, {"title": "RAHASIA_Amoxicillin"})

    event = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="reminder", action="update").first()
    assert event is not None
    assert event.changed_fields_json == ["private_details"]
    assert "RAHASIA" not in json.dumps(event.to_dict())
    assert "Amoxicillin" not in json.dumps(event.to_dict())


def test_delete_reminder_produces_audit_event(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"]).get_json()["id"]

    _delete_reminder(client, user["token"], child["id"], reminder_id)

    event = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="reminder", action="delete").first()
    assert event is not None
    assert event.entity_id == reminder_id


def test_complete_and_skip_occurrences_produce_distinct_audit_entity_types(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    started_at = datetime(2026, 8, 21, 8, 0, 0)
    reminder_id = _create_reminder(client, user["token"], child["id"], recurrence="daily", scheduled_at=started_at.isoformat()).get_json()["id"]

    _act(client, user["token"], child["id"], reminder_id, "2026-08-21", "complete")
    _act(client, user["token"], child["id"], reminder_id, "2026-08-22", "skip")

    completed_events = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="reminder_occurrence_completed").all()
    skipped_events = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="reminder_occurrence_skipped").all()
    assert len(completed_events) == 1
    assert len(skipped_events) == 1
    assert completed_events[0].action == "create"
    assert skipped_events[0].action == "create"


# --------------------------------------------------------------------------
# "Catat sekarang" — occurrence bisa ditautkan ke 1 catatan perawatan
# yang BENERAN baru disimpan (bukan dibikin otomatis).
# --------------------------------------------------------------------------


def test_complete_occurrence_can_link_to_a_medication_log_belonging_to_the_same_child(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"], reminder_type="medication").get_json()["id"]

    log_resp = client.post(
        f"/api/children/{child['id']}/medication-logs",
        json={"medication_name": "Obat", "timestamp": FAKE_NOW.isoformat()},
        headers={**auth_headers(user["token"]), "X-Idempotency-Key": "med-1"},
    )
    assert log_resp.status_code == 201
    log_id = log_resp.get_json()["id"]

    occ_key = FAKE_NOW.date().isoformat()
    resp = _act(client, user["token"], child["id"], reminder_id, occ_key, "complete",
                body={"linked_log_type": "medication_log", "linked_log_id": log_id})
    assert resp.status_code == 201
    assert resp.get_json()["linked_log_type"] == "medication_log"
    assert resp.get_json()["linked_log_id"] == log_id


def test_complete_occurrence_rejects_linking_a_log_from_a_different_child(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child_a = create_child(client, user["token"], name="Anak A")
    child_b = create_child(client, user["token"], name="Anak B")
    reminder_id = _create_reminder(client, user["token"], child_a["id"], reminder_type="medication").get_json()["id"]

    log_resp = client.post(
        f"/api/children/{child_b['id']}/medication-logs",
        json={"medication_name": "Obat", "timestamp": FAKE_NOW.isoformat()},
        headers={**auth_headers(user["token"]), "X-Idempotency-Key": "med-2"},
    )
    log_id = log_resp.get_json()["id"]

    occ_key = FAKE_NOW.date().isoformat()
    resp = _act(client, user["token"], child_a["id"], reminder_id, occ_key, "complete",
                body={"linked_log_type": "medication_log", "linked_log_id": log_id})
    assert resp.status_code == 400
    assert ReminderAction.query.filter_by(reminder_id=reminder_id).count() == 0


def test_complete_occurrence_rejects_unsupported_linked_log_type(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"]).get_json()["id"]

    occ_key = FAKE_NOW.date().isoformat()
    resp = _act(client, user["token"], child["id"], reminder_id, occ_key, "complete",
                body={"linked_log_type": "illness_log", "linked_log_id": 1})
    assert resp.status_code == 400


def test_general_reminder_completion_does_not_require_or_create_a_log(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    reminder_id = _create_reminder(client, user["token"], child["id"], reminder_type="general").get_json()["id"]

    occ_key = FAKE_NOW.date().isoformat()
    resp = _act(client, user["token"], child["id"], reminder_id, occ_key, "complete")
    assert resp.status_code == 201
    assert resp.get_json()["linked_log_type"] is None


# --------------------------------------------------------------------------
# 17. Regresi endpoint lain yang sudah ada.
# --------------------------------------------------------------------------


def test_existing_stats_endpoint_still_works_after_reminders_addition(client, monkeypatch):
    _freeze_now(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.get(f"/api/children/{child['id']}/stats?days=7", headers=auth_headers(user["token"]))
    assert resp.status_code == 200
