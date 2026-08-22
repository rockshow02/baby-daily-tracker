"""
Test `POST /children/import-json` (dan sekilas `GET /children/<id>/export-json`)
— fokus ke Issue 1 (review pasca Caregiver Roles & Permissions Phase 1):
import JSON SEBELUMNYA masih nyisipin `ChildCaregiver(role="owner")`, yang
sekarang melanggar CHECK constraint `role IN ('editor','viewer')` dan bisa
bikin import gagal 500. Lihat backend/docs/ROLES_PERMISSIONS.md bagian
"Import JSON" buat kontrak lengkapnya.

SEMUA test pakai fixture `client` (SQLite in-memory), TIDAK PERNAH
menyentuh instance/tracker.db asli.
"""
import pytest
from sqlalchemy.orm import Session

from extensions import db
from models import Child, ChildCaregiver, FeedingLog, SleepLog
from tests.conftest import auth_headers, create_child, register


def _minimal_import_payload(**overrides):
    payload = {
        "export_version": 1,
        "exported_at": "2026-01-01T00:00:00Z",
        "child": {
            "name": "Anak Import",
            "birth_date": "2026-01-01",
            "gender": "L",
            "birth_weight_kg": 3.2,
            "birth_height_cm": 50,
        },
        "feeding_logs": [
            {"timestamp": "2026-01-10T08:00:00", "feed_type": "asi_langsung", "duration_minutes": 10},
        ],
    }
    payload.update(overrides)
    return payload


def _import(client, token, payload):
    return client.post("/api/children/import-json", json=payload, headers=auth_headers(token))


# --------------------------------------------------------------------------
# 1-3. Import sukses, Child.user_id = pengimpor, resolve role owner via API.
# --------------------------------------------------------------------------


def test_valid_import_returns_success_status(client):
    user = register(client)
    resp = _import(client, user["token"], _minimal_import_payload())
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["success"] is True


def test_imported_child_user_id_equals_authenticated_importer(client):
    user = register(client)
    resp = _import(client, user["token"], _minimal_import_payload())
    child_id = resp.get_json()["child"]["id"]

    row = db.session.get(Child, child_id)
    assert row.user_id == user["id"]


def test_imported_child_resolves_as_owner_via_get_and_list(client):
    user = register(client)
    resp = _import(client, user["token"], _minimal_import_payload())
    child_id = resp.get_json()["child"]["id"]

    # respons import itu sendiri udah nyertain role
    assert resp.get_json()["child"]["role"] == "owner"

    get_resp = client.get(f"/api/children/{child_id}", headers=auth_headers(user["token"]))
    assert get_resp.status_code == 200
    assert get_resp.get_json()["role"] == "owner"

    list_resp = client.get("/api/children", headers=auth_headers(user["token"]))
    assert list_resp.status_code == 200
    imported = next(c for c in list_resp.get_json() if c["id"] == child_id)
    assert imported["role"] == "owner"


# --------------------------------------------------------------------------
# 4-5. Nggak ada baris ChildCaregiver, apalagi role='owner', buat pengimpor.
# --------------------------------------------------------------------------


def test_no_childcaregiver_row_exists_for_the_imported_owner(client):
    user = register(client)
    resp = _import(client, user["token"], _minimal_import_payload())
    child_id = resp.get_json()["child"]["id"]

    cc = ChildCaregiver.query.filter_by(child_id=child_id, user_id=user["id"]).first()
    assert cc is None


def test_no_membership_with_role_owner_is_ever_created(client):
    user = register(client)
    _import(client, user["token"], _minimal_import_payload())
    _import(client, user["token"], _minimal_import_payload())  # dua kali, buat mastiin

    assert ChildCaregiver.query.filter_by(role="owner").count() == 0


# --------------------------------------------------------------------------
# 6. Import jalan normal dengan CHECK constraint (editor/viewer doang) aktif.
# --------------------------------------------------------------------------


def test_check_constraint_genuinely_rejects_a_raw_owner_role_insert(client):
    """
    Bukti CHECK constraint-nya BENERAN aktif (bukan cuma diasumsikan) —
    kalau baris ini dulu masih nyisipin role='owner' langsung, insert
    kayak gini bakal gagal PERSIS kayak yang dites di sini.
    """
    user = register(client)
    child = create_child(client, user["token"])

    with pytest.raises(Exception):
        db.session.add(ChildCaregiver(child_id=child["id"], user_id=user["id"], role="owner"))
        db.session.commit()
    db.session.rollback()


def test_import_succeeds_with_the_check_constraint_active(client):
    """Regresi langsung buat bug Issue 1: import DULU gagal 500 di sini karena constraint ini."""
    user = register(client)
    resp = _import(client, user["token"], _minimal_import_payload())
    assert resp.status_code == 201


# --------------------------------------------------------------------------
# 7. Membership editor/viewer di file backup TIDAK PERNAH diterima.
# --------------------------------------------------------------------------


def test_membership_like_fields_in_backup_json_are_completely_ignored(client):
    user = register(client)
    payload = _minimal_import_payload()
    # field-field ini TIDAK PERNAH ada di export_json() asli, tapi kalau
    # ada (file backup direkayasa manual) endpoint ini HARUS ngabaikan
    # total, bukan dibaca sama sekali.
    payload["caregivers"] = [{"user_id": 999, "role": "editor"}]
    payload["memberships"] = [{"user_id": 999, "role": "viewer"}]

    resp = _import(client, user["token"], payload)
    assert resp.status_code == 201
    child_id = resp.get_json()["child"]["id"]
    assert ChildCaregiver.query.filter_by(child_id=child_id).count() == 0


# --------------------------------------------------------------------------
# 8. user_id/owner_id/created_by_user_id/role dipalsukan di JSON TIDAK
#    PERNAH mengubah kepemilikan atau eskalasi akses.
# --------------------------------------------------------------------------


def test_forged_ownership_fields_in_child_json_cannot_change_ownership(client):
    user = register(client)
    other_user = register(client, name="Korban", email="korban-forge@example.com")

    payload = _minimal_import_payload()
    payload["child"]["user_id"] = other_user["id"]
    payload["child"]["owner_id"] = other_user["id"]
    payload["child"]["created_by_user_id"] = other_user["id"]
    payload["child"]["role"] = "owner"
    payload["user_id"] = other_user["id"]
    payload["owner_id"] = other_user["id"]

    resp = _import(client, user["token"], payload)
    assert resp.status_code == 201
    child_id = resp.get_json()["child"]["id"]

    row = db.session.get(Child, child_id)
    assert row.user_id == user["id"]  # bukan other_user

    # korban yang dipalsukan ID-nya TIDAK dapet akses apa pun ke anak ini
    other_get = client.get(f"/api/children/{child_id}", headers=auth_headers(other_user["token"]))
    assert other_get.status_code == 404


def test_forged_created_by_user_id_on_a_log_entry_is_ignored(client):
    user = register(client)
    other_user = register(client, name="Korban2", email="korban-forge2@example.com")

    payload = _minimal_import_payload()
    payload["feeding_logs"][0]["created_by_user_id"] = other_user["id"]

    resp = _import(client, user["token"], payload)
    assert resp.status_code == 201
    child_id = resp.get_json()["child"]["id"]

    log = FeedingLog.query.filter_by(child_id=child_id).first()
    assert log.created_by_user_id == user["id"]  # bukan other_user


# --------------------------------------------------------------------------
# 9-10. Atomisitas: input tidak valid / kegagalan paksa -> nggak ada data
# sebagian yang nyangkut.
# --------------------------------------------------------------------------


def test_malformed_import_produces_no_partial_child_or_log_rows(client):
    user = register(client)
    children_before = Child.query.count()

    payload = _minimal_import_payload()
    del payload["feeding_logs"][0]["feed_type"]  # field wajib dibuang -> KeyError internal

    resp = _import(client, user["token"], payload)
    assert resp.status_code == 400

    assert Child.query.count() == children_before
    assert FeedingLog.query.count() == 0


def test_invalid_birth_date_format_returns_400_not_500(client):
    user = register(client)
    payload = _minimal_import_payload()
    payload["child"]["birth_date"] = "tanggal-ngasal"

    resp = _import(client, user["token"], payload)
    assert resp.status_code == 400
    assert Child.query.count() == 0


def test_forced_commit_failure_rolls_back_child_and_all_records(client, monkeypatch):
    user = register(client)
    payload = _minimal_import_payload(
        sleep_logs=[{"start_time": "2026-01-10T20:00:00", "sleep_type": "malam"}],
    )

    def raise_commit(self, *a, **k):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(Session, "commit", raise_commit)

    resp = _import(client, user["token"], payload)
    assert resp.status_code == 500

    # sama alasannya kayak test_audit_trail.py:test_commit_failure_rolls_back...
    # — client fixture nahan 1 app context manual, jadi rollback eksplisit
    # di sini nyimulasiin teardown request asli yang belum sempat jalan.
    db.session.rollback()
    assert Child.query.count() == 0
    assert FeedingLog.query.count() == 0
    assert SleepLog.query.count() == 0


# --------------------------------------------------------------------------
# 11. Export -> import round-trip nggak regresi (data yang didukung tetap sama).
# --------------------------------------------------------------------------


def test_export_then_import_round_trip_preserves_supported_data(client):
    user = register(client)
    original = create_child(client, user["token"])

    client.post(
        f"/api/children/{original['id']}/feeding-logs",
        json={"feed_type": "sufor", "duration_minutes": 15, "volume_ml": 90},
        headers={**auth_headers(user["token"]), "X-Idempotency-Key": "k1"},
    )
    client.post(
        f"/api/children/{original['id']}/sleep-logs",
        json={"start_time": "2026-01-10T20:00:00", "sleep_type": "malam"},
        headers={**auth_headers(user["token"]), "X-Idempotency-Key": "k2"},
    )

    export_resp = client.get(f"/api/children/{original['id']}/export-json", headers=auth_headers(user["token"]))
    assert export_resp.status_code == 200
    backup = export_resp.get_json()

    import_resp = _import(client, user["token"], backup)
    assert import_resp.status_code == 201
    new_child_id = import_resp.get_json()["child"]["id"]

    assert FeedingLog.query.filter_by(child_id=new_child_id).count() == 1
    assert SleepLog.query.filter_by(child_id=new_child_id).count() == 1
    assert db.session.get(Child, new_child_id).user_id == user["id"]


# --------------------------------------------------------------------------
# Kebersihan foto pas rollback (requirement #9)
# --------------------------------------------------------------------------


def test_orphaned_photo_file_is_removed_when_import_fails_after_photo_write(client, monkeypatch, tmp_path):
    """
    `_uploads_dir()` di-monkeypatch ke direktori temp KHUSUS test ini
    (BUKAN backend/uploads/ asli — itu folder foto pengguna beneran,
    nggak boleh disentuh test sama sekali) — biar test ini bisa
    ngebuktiin file yang ke-orphan beneran kehapus, TANPA risiko
    ninggalin sampah di folder upload asli kalau fix-nya somehow salah.
    """
    import base64
    import os
    import routes.backup_routes as backup_routes_module

    monkeypatch.setattr(backup_routes_module, "_uploads_dir", lambda: str(tmp_path))

    user = register(client)
    tiny_png = base64.b64encode(b"not-a-real-png-but-bytes").decode("ascii")
    payload = _minimal_import_payload(
        child={**_minimal_import_payload()["child"], "photo_base64": tiny_png, "photo_ext": "png"},
    )
    # log entry yang bikin transaksi gagal SETELAH foto ditulis
    del payload["feeding_logs"][0]["feed_type"]

    resp = _import(client, user["token"], payload)
    assert resp.status_code == 400

    assert os.listdir(tmp_path) == []  # nggak ada file yang nyangkut di direktori temp ini
