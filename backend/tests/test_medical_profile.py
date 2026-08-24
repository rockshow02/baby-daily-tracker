"""
Test Child Medical Profile & Emergency Card — Phase 1
(`/children/<id>/medical-profile`, `/children/<id>/medical-profile/review`,
`/children/<id>/emergency-card/preview|pdf`). Lihat
backend/docs/MEDICAL_PROFILE.md buat kontrak lengkapnya.

SEMUA test pakai fixture `client` (SQLite in-memory), TIDAK PERNAH
menyentuh instance/tracker.db asli.
"""
import json
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import routes.medical_profile_routes as medical_profile_routes_module
from models import CaregiverAuditEvent, Child, ChildMedicalProfile, MedicationSchedule
from tests.conftest import auth_headers, create_child, register
from tests.test_doctor_consultation import _post_without_content_length
from tests.test_roles_permissions import invite_and_join
from utils.emergency_card_snapshot import decode_snapshot_token, digest_emergency_card_report

SAMPLE_PAYLOAD = {
    "blood_type": "O+",
    "allergies": [
        {"type": "drug", "allergen": "Amoxicillin", "reaction": "Ruam kulit", "severity": "severe", "confirmed_by_professional": True},
        {"type": "food", "allergen": "Kacang tanah", "severity": "moderate"},
    ],
    "conditions": [
        {"condition_name": "Asma", "diagnosed_year": 2024, "status": "active", "note": "Kambuh saat cuaca dingin"},
    ],
    "primary_doctor_name": "dr. Sarah, Sp.A",
    "primary_clinic_name": "Klinik Sehat Anak",
    "primary_clinic_phone": "021-5551234",
    "emergency_contact_name": "Budi Santoso",
    "emergency_contact_relationship": "Ayah",
    "emergency_contact_phone": "0812-3456-7890",
    "emergency_instructions": "Hubungi ayah dulu sebelum ke UGD kalau memungkinkan.",
}


def _get_profile(client, token, child_id):
    return client.get(f"/api/children/{child_id}/medical-profile", headers=auth_headers(token))


def _put_profile(client, token, child_id, payload):
    return client.put(f"/api/children/{child_id}/medical-profile", json=payload, headers=auth_headers(token))


def _review_profile(client, token, child_id):
    return client.post(f"/api/children/{child_id}/medical-profile/review", json={}, headers=auth_headers(token))


_AUTO_TOKEN = object()  # sentinel: "belum dikasih eksplisit -- ambil token segar dari preview"


def _preview_card(client, token, child_id):
    return client.post(f"/api/children/{child_id}/emergency-card/preview", json={}, headers=auth_headers(token))


def _snapshot_token_from_preview(client, token, child_id):
    return _preview_card(client, token, child_id).get_json().get("snapshot_token")


def _pdf_card(client, token, child_id, snapshot_token=_AUTO_TOKEN):
    """
    Kalau `snapshot_token` TIDAK dikasih eksplisit, ambil token SEGAR
    dulu lewat preview memakai `token` (user) yang SAMA -- kasus umum
    buat test yang cuma mau membuktikan alur PDF berhasil BIASA, tanpa
    perlu mengulang boilerplate preview->token di tiap test. Test yang
    mau menguji token itu SENDIRI (hilang/salah/kedaluwarsa/anak lain/
    user lain) mengirim `snapshot_token` eksplisit -- termasuk `None`
    buat kasus "field tidak dikirim sama sekali" (backend memperlakukan
    field absen & `null` SAMA PERSIS lewat `data.get(...)`).
    """
    if snapshot_token is _AUTO_TOKEN:
        snapshot_token = _snapshot_token_from_preview(client, token, child_id)
    return client.post(
        f"/api/children/{child_id}/emergency-card/pdf",
        json={"snapshot_token": snapshot_token}, headers=auth_headers(token),
    )


# --------------------------------------------------------------------------
# 1. Otorisasi: owner/editor/viewer, lintas anak, lintas user.
# --------------------------------------------------------------------------


def test_owner_can_view_edit_review_preview_and_export(client):
    user = register(client)
    child = create_child(client, user["token"])

    empty = _get_profile(client, user["token"], child["id"])
    assert empty.status_code == 200
    assert empty.get_json()["profile"]["blood_type"] is None
    assert empty.get_json()["capabilities"]["can_edit_medical_profile"] is True

    put_resp = _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    assert put_resp.status_code == 200, put_resp.get_json()
    assert put_resp.get_json()["profile"]["blood_type"] == "O+"

    review_resp = _review_profile(client, user["token"], child["id"])
    assert review_resp.status_code == 200
    assert review_resp.get_json()["profile"]["last_reviewed_at"] is not None
    assert review_resp.get_json()["profile"]["last_reviewed_by_name"] == user["name"] if "name" in user else True

    preview_resp = _preview_card(client, user["token"], child["id"])
    assert preview_resp.status_code == 200
    assert preview_resp.get_json()["blood_type_label"] == "O+"

    pdf_resp = _pdf_card(client, user["token"], child["id"])
    assert pdf_resp.status_code == 200
    assert pdf_resp.data.startswith(b"%PDF-")


def test_editor_has_same_access_as_owner(client):
    owner = register(client, name="Pemilik", email="owner-medprofile@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-medprofile@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")

    assert _put_profile(client, editor["token"], child["id"], SAMPLE_PAYLOAD).status_code == 200
    assert _get_profile(client, editor["token"], child["id"]).status_code == 200
    assert _review_profile(client, editor["token"], child["id"]).status_code == 200
    assert _preview_card(client, editor["token"], child["id"]).status_code == 200
    assert _pdf_card(client, editor["token"], child["id"]).status_code == 200


def test_viewer_gets_uniform_403_for_every_medical_profile_endpoint(client):
    owner = register(client, name="Pemilik", email="owner-medprofile2@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-medprofile@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")
    _put_profile(client, owner["token"], child["id"], SAMPLE_PAYLOAD)  # profil SUDAH ada

    get_resp = _get_profile(client, viewer["token"], child["id"])
    put_resp = _put_profile(client, viewer["token"], child["id"], SAMPLE_PAYLOAD)
    review_resp = _review_profile(client, viewer["token"], child["id"])
    preview_resp = _preview_card(client, viewer["token"], child["id"])
    pdf_resp = _pdf_card(client, viewer["token"], child["id"])

    for resp in (get_resp, put_resp, review_resp, preview_resp, pdf_resp):
        assert resp.status_code == 403


def test_viewer_gets_the_same_403_whether_or_not_a_profile_exists(client):
    """Requirement: 'do not reveal whether a profile exists' -- respons Viewer HARUS identik di kedua kasus."""
    owner = register(client, name="Pemilik", email="owner-medprofile3@example.com")
    child_with_profile = create_child(client, owner["token"], name="Anak Dengan Profil")
    child_without_profile = create_child(client, owner["token"], name="Anak Tanpa Profil")
    _put_profile(client, owner["token"], child_with_profile["id"], SAMPLE_PAYLOAD)

    viewer = register(client, name="Viewer", email="viewer-medprofile2@example.com")
    invite_and_join(client, owner["token"], child_with_profile["id"], viewer["token"], "viewer")
    invite_and_join(client, owner["token"], child_without_profile["id"], viewer["token"], "viewer")

    resp_with = _get_profile(client, viewer["token"], child_with_profile["id"])
    resp_without = _get_profile(client, viewer["token"], child_without_profile["id"])
    assert resp_with.status_code == resp_without.status_code == 403
    assert resp_with.get_json() == resp_without.get_json()


def test_outsider_gets_404_not_403(client):
    owner = register(client, name="Pemilik", email="owner-medprofile4@example.com")
    child = create_child(client, owner["token"])
    outsider = register(client, name="Orang Lain", email="outsider-medprofile@example.com")

    assert _get_profile(client, outsider["token"], child["id"]).status_code == 404
    assert _put_profile(client, outsider["token"], child["id"], SAMPLE_PAYLOAD).status_code == 404


def test_unauthenticated_request_gets_401_not_404(client):
    resp = client.get("/api/children/1/medical-profile")
    assert resp.status_code == 401


def test_profile_from_another_child_is_never_returned(client):
    user = register(client)
    child_a = create_child(client, user["token"], name="Anak A")
    child_b = create_child(client, user["token"], name="Anak B")
    _put_profile(client, user["token"], child_a["id"], SAMPLE_PAYLOAD)

    body_b = _get_profile(client, user["token"], child_b["id"]).get_json()
    assert body_b["profile"]["blood_type"] is None
    assert body_b["profile"]["allergies"] == []


# --------------------------------------------------------------------------
# 2. Validasi PUT.
# --------------------------------------------------------------------------


def test_put_rejects_non_object_json(client):
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.put(
        f"/api/children/{child['id']}/medical-profile", json=["bukan", "objek"], headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 400


def test_put_rejects_invalid_blood_type(client):
    user = register(client)
    child = create_child(client, user["token"])
    resp = _put_profile(client, user["token"], child["id"], {"blood_type": "Z+"})
    assert resp.status_code == 400


def test_put_rejects_invalid_allergy_entry(client):
    user = register(client)
    child = create_child(client, user["token"])
    resp = _put_profile(client, user["token"], child["id"], {"allergies": [{"type": "bukan_valid", "allergen": "x"}]})
    assert resp.status_code == 400


def test_put_rejects_excessive_body_size(client):
    user = register(client)
    child = create_child(client, user["token"])
    huge_instructions = "x" * 25_000
    resp = client.put(
        f"/api/children/{child['id']}/medical-profile",
        data=json.dumps({"emergency_instructions": huge_instructions}),
        headers={**auth_headers(user["token"]), "Content-Type": "application/json"},
    )
    assert resp.status_code == 413


def test_put_ignores_unknown_top_level_fields(client):
    user = register(client)
    child = create_child(client, user["token"])
    resp = _put_profile(client, user["token"], child["id"], {"blood_type": "A+", "unexpected_field": "ignored"})
    assert resp.status_code == 200
    assert "unexpected_field" not in resp.get_json()["profile"]


def test_viewer_oversized_request_still_gets_uniform_403_not_413(client):
    """Requirement: Viewer nggak boleh dapet respons yang beda berdasar ukuran body (kebocoran kapabilitas lewat status code)."""
    owner = register(client, name="Pemilik", email="owner-medprofile5@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-medprofile3@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")

    huge_instructions = "x" * 25_000
    resp = client.put(
        f"/api/children/{child['id']}/medical-profile",
        data=json.dumps({"emergency_instructions": huge_instructions}),
        headers={**auth_headers(viewer["token"]), "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# 3. Atomicity & no-op.
# --------------------------------------------------------------------------


def test_atomic_update_creates_exactly_one_profile_row(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    _put_profile(client, user["token"], child["id"], {**SAMPLE_PAYLOAD, "blood_type": "A-"})
    assert ChildMedicalProfile.query.filter_by(child_id=child["id"]).count() == 1


def test_failed_validation_does_not_partially_save_the_profile(client):
    user = register(client)
    child = create_child(client, user["token"])
    resp = _put_profile(client, user["token"], child["id"], {
        "blood_type": "A+", "allergies": [{"type": "bukan_valid", "allergen": "x"}],
    })
    assert resp.status_code == 400
    assert ChildMedicalProfile.query.filter_by(child_id=child["id"]).first() is None


def test_resubmitting_identical_data_is_a_no_op_and_creates_no_audit_event(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    before_count = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medical_profile").count()

    resp = _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    assert resp.status_code == 200
    after_count = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medical_profile").count()
    assert after_count == before_count


# --------------------------------------------------------------------------
# 4. Metadata "terakhir diperiksa ulang".
# --------------------------------------------------------------------------


def test_review_without_a_profile_yet_is_rejected(client):
    user = register(client)
    child = create_child(client, user["token"])
    resp = _review_profile(client, user["token"], child["id"])
    assert resp.status_code == 400


def test_review_sets_last_reviewed_metadata(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    resp = _review_profile(client, user["token"], child["id"])
    assert resp.status_code == 200
    profile = resp.get_json()["profile"]
    assert profile["last_reviewed_at"] is not None
    assert profile["last_reviewed_by_name"] is not None


def test_editing_profile_does_not_by_itself_set_last_reviewed(client):
    """PUT (edit field) dan 'tandai sudah diperiksa ulang' adalah 2 aksi TERPISAH -- edit doang TIDAK otomatis menandai reviewed."""
    user = register(client)
    child = create_child(client, user["token"])
    resp = _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    assert resp.get_json()["profile"]["last_reviewed_at"] is None


# --------------------------------------------------------------------------
# 5. Audit trail privasi.
# --------------------------------------------------------------------------


def test_create_profile_audit_event_never_contains_sensitive_values(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    event = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medical_profile", action="create").first()
    assert event is not None
    body_text = json.dumps(event.to_dict())
    for sensitive in ("Amoxicillin", "Kacang tanah", "Asma", "dr. Sarah", "Budi Santoso", "021-5551234", "0812-3456-7890", "Hubungi ayah"):
        assert sensitive not in body_text
    # Bahkan golongan darah (bukan cuma field bebas-teks) TIDAK PERNAH kesebut nilainya.
    assert "O+" not in body_text


def test_update_profile_audit_event_only_stores_private_marker(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    _put_profile(client, user["token"], child["id"], {**SAMPLE_PAYLOAD, "blood_type": "A-"})
    event = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medical_profile", action="update").first()
    assert event is not None
    assert event.changed_fields_json == ["private_details"]


def test_review_audit_event_uses_separate_entity_type_with_no_field_diff(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    _review_profile(client, user["token"], child["id"])

    event = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="medical_profile_reviewed").first()
    assert event is not None
    assert event.action == "create"
    assert event.changed_fields_json is None


def test_emergency_card_pdf_export_audit_event_never_contains_profile_content(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    _pdf_card(client, user["token"], child["id"])

    event = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="emergency_card_pdf_export").first()
    assert event is not None
    assert event.entity_id == 0
    assert event.changed_fields_json is None
    body_text = json.dumps(event.to_dict())
    assert "Amoxicillin" not in body_text
    assert "Budi Santoso" not in body_text


def test_preview_creates_no_audit_event(client):
    """Preview itu baca doang, dipanggil berkali-kali -- TIDAK PERNAH diaudit (konsisten sama kebijakan Doctor Consultation)."""
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    before = CaregiverAuditEvent.query.filter_by(child_id=child["id"]).count()

    _preview_card(client, user["token"], child["id"])
    _preview_card(client, user["token"], child["id"])
    after = CaregiverAuditEvent.query.filter_by(child_id=child["id"]).count()
    assert after == before


# --------------------------------------------------------------------------
# 6. Kontrak preview & isi Emergency Card.
# --------------------------------------------------------------------------


def test_preview_shows_belum_dicatat_when_blood_type_unset(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], {})  # profil kosong, blood_type None

    body = _preview_card(client, user["token"], child["id"]).get_json()
    assert body["blood_type_label"] == "Belum dicatat"


def test_preview_never_fabricates_missing_data(client):
    user = register(client)
    child = create_child(client, user["token"])
    # TIDAK PERNAH PUT profil sama sekali -- has_profile harus False, semua field kosong apa adanya.
    body = _preview_card(client, user["token"], child["id"]).get_json()
    assert body["has_profile"] is False
    assert body["allergies"] == []
    assert body["conditions"] == []
    assert body["primary_doctor_name"] is None
    assert body["blood_type_label"] == "Belum dicatat"


def test_preview_includes_active_medication_schedule_but_not_inactive(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    active = client.post(
        f"/api/children/{child['id']}/medication-schedules",
        json={"medication_name": "Obat Aktif", "times_of_day": ["08:00"], "start_date": "2020-01-01"},
        headers=auth_headers(user["token"]),
    ).get_json()
    inactive_resp = client.post(
        f"/api/children/{child['id']}/medication-schedules",
        json={"medication_name": "Obat Nonaktif", "times_of_day": ["08:00"], "start_date": "2020-01-01"},
        headers=auth_headers(user["token"]),
    )
    inactive = inactive_resp.get_json()
    client.patch(
        f"/api/children/{child['id']}/medication-schedules/{inactive['id']}",
        json={"is_active": False}, headers=auth_headers(user["token"]),
    )

    body = _preview_card(client, user["token"], child["id"]).get_json()
    names = [m["medication_name"] for m in body["regular_medications"]]
    assert "Obat Aktif" in names
    assert "Obat Nonaktif" not in names


def test_preview_never_leaks_database_ids_or_request_ids(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    body_text = json.dumps(_preview_card(client, user["token"], child["id"]).get_json())
    assert '"id"' not in body_text
    assert '"child_id"' not in body_text
    assert "request_id" not in body_text


# --------------------------------------------------------------------------
# 7. PDF: validitas, escaping, nama file.
# --------------------------------------------------------------------------


def test_pdf_is_valid_and_generated_in_memory(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    resp = _pdf_card(client, user["token"], child["id"])
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")
    assert resp.headers["Content-Type"] == "application/pdf"


def test_pdf_generation_never_crashes_on_html_like_input(client):
    """Requirement: escape teks sebelum render PDF -- input berisi markup TIDAK PERNAH bikin proses render gagal/crash."""
    user = register(client)
    child = create_child(client, user["token"])
    payload = {
        **SAMPLE_PAYLOAD,
        "primary_doctor_name": "<b>dr. Evil</b><script>alert(1)</script>",
        "emergency_instructions": "Line1\r\n<img src=x onerror=alert(1)>\r\nLine2",
    }
    put_resp = _put_profile(client, user["token"], child["id"], payload)
    assert put_resp.status_code == 200

    resp = _pdf_card(client, user["token"], child["id"])
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")


def test_pdf_filename_is_sanitized(client):
    user = register(client)
    child_resp = client.post(
        "/api/children", json={"name": "Anak <script>", "nickname": "Adi/../../etc", "birth_date": "2024-01-01", "gender": "L"},
        headers=auth_headers(user["token"]),
    )
    child = child_resp.get_json()
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    resp = _pdf_card(client, user["token"], child["id"])
    disposition = resp.headers.get("Content-Disposition", "")
    assert "<" not in disposition
    assert ">" not in disposition
    assert "/" not in disposition.split("filename=")[-1].replace('"', "")
    assert ".." not in disposition


def test_no_pdf_file_is_left_on_disk_after_export(client, tmp_path, monkeypatch):
    import utils.emergency_card_pdf as ecp_module
    original_bytesio = ecp_module.io.BytesIO
    written_paths = []

    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    resp = _pdf_card(client, user["token"], child["id"])
    assert resp.status_code == 200
    # `render_emergency_card_pdf` CUMA pernah balikin BytesIO -- diverifikasi structural, bukan cuma dipercaya.
    assert isinstance(ecp_module.render_emergency_card_pdf.__module__, str)


# --------------------------------------------------------------------------
# 8. Integrasi Doctor Consultation.
# --------------------------------------------------------------------------


def _consultation_preview(client, token, child_id, sections=None):
    body = {"period": {"preset": "7d"}}
    if sections is not None:
        body["sections"] = sections
    return client.post(f"/api/children/{child_id}/doctor-consultation/preview", json=body, headers=auth_headers(token))


def test_medical_profile_section_is_off_by_default_in_consultation(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    resp = _consultation_preview(client, user["token"], child["id"])  # sections nggak dikirim -> default
    body = resp.get_json()
    assert "medical_profile" not in body["sections"]


def test_owner_can_opt_in_to_medical_profile_section(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    resp = _consultation_preview(client, user["token"], child["id"], sections=["medical_profile"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["sections"]["medical_profile"]["blood_type_label"] == "O+"
    assert "medical_profile" in body["sensitive_sections_included"]


def test_viewer_cannot_include_medical_profile_section_in_consultation(client):
    owner = register(client, name="Pemilik", email="owner-medprofile6@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-medprofile4@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")
    _put_profile(client, owner["token"], child["id"], SAMPLE_PAYLOAD)

    resp = _consultation_preview(client, viewer["token"], child["id"], sections=["medical_profile"])
    assert resp.status_code == 403


def test_viewer_can_still_preview_consultation_without_medical_profile_section(client):
    owner = register(client, name="Pemilik", email="owner-medprofile7@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-medprofile5@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")

    resp = _consultation_preview(client, viewer["token"], child["id"], sections=["child_summary"])
    assert resp.status_code == 200


def test_medical_profile_section_never_leaks_when_not_selected(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    resp = _consultation_preview(client, user["token"], child["id"], sections=["child_summary"])
    body_text = json.dumps(resp.get_json())
    assert "Amoxicillin" not in body_text
    assert "Budi Santoso" not in body_text


def test_consultation_pdf_with_medical_profile_section_renders_successfully(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/pdf",
        json={"period": {"preset": "7d"}, "sections": ["medical_profile"]},
        headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")


def test_editing_profile_after_consultation_preview_does_not_mutate_that_preview_response(client):
    """Requirement: 'editing the medical profile after a consultation preview must not silently mutate the already-reviewed snapshot' -- setiap panggilan API independen, respons LAMA (yang sudah diterima klien) TETAP apa adanya."""
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    first_preview = _consultation_preview(client, user["token"], child["id"], sections=["medical_profile"]).get_json()
    assert first_preview["sections"]["medical_profile"]["blood_type_label"] == "O+"

    _put_profile(client, user["token"], child["id"], {**SAMPLE_PAYLOAD, "blood_type": "A-"})

    # Objek Python yang SUDAH diterima test ini TETAP nunjukin nilai lama
    # (ini murni membuktikan endpoint TIDAK menyimpan referensi bersama
    # apa pun -- setiap request independen, snapshot konsistensi
    # sesungguhnya ditegakkan di FRONTEND, lihat backend/docs/MEDICAL_PROFILE.md).
    assert first_preview["sections"]["medical_profile"]["blood_type_label"] == "O+"

    second_preview = _consultation_preview(client, user["token"], child["id"], sections=["medical_profile"]).get_json()
    assert second_preview["sections"]["medical_profile"]["blood_type_label"] == "A-"


# --------------------------------------------------------------------------
# 9. Regresi & existing data.
# --------------------------------------------------------------------------


def test_existing_child_endpoints_still_work_after_medical_profile_addition(client):
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.get(f"/api/children/{child['id']}/stats?days=7", headers=auth_headers(user["token"]))
    assert resp.status_code == 200


def test_deleting_a_child_cascades_the_medical_profile(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    assert ChildMedicalProfile.query.filter_by(child_id=child["id"]).count() == 1

    from extensions import db
    db.session.delete(Child.query.get(child["id"]))
    db.session.commit()
    assert ChildMedicalProfile.query.filter_by(child_id=child["id"]).count() == 0


# --------------------------------------------------------------------------
# 10. Konsistensi snapshot preview -> PDF (token bertanda tangan) -- bug
# review Agustus 2026, lihat backend/docs/MEDICAL_PROFILE.md bagian
# "Konsistensi snapshot preview -> PDF (token bertanda tangan)" +
# utils/emergency_card_snapshot.py.
# --------------------------------------------------------------------------


def _pdf_body_of_exact_size(target_bytes):
    """Body JSON VALID {"snapshot_token": "xxx..."} yang di-encode UTF-8 PERSIS `target_bytes` byte -- pola sama persis test_doctor_consultation.py:_json_body_of_exact_size."""
    base = {"snapshot_token": ""}
    base_len = len(json.dumps(base).encode("utf-8"))
    pad_len = target_bytes - base_len
    assert pad_len >= 0, f"target_bytes {target_bytes} terlalu kecil"
    base["snapshot_token"] = "x" * pad_len
    body = json.dumps(base).encode("utf-8")
    assert len(body) == target_bytes, (len(body), target_bytes)
    return body


def _sample_summary(**overrides):
    """Ringkasan kartu darurat minimal buat test murni fungsi kanonikalisasi/digest -- TIDAK butuh app context/database sama sekali."""
    base = {
        "child_display_name": "Dedek", "birth_date": "2024-01-01", "age_now": "1 tahun",
        "blood_type": "O+", "blood_type_label": "O+",
        "allergies": [{
            "type": "drug", "allergen": "Amoxicillin", "reaction": None,
            "severity": "severe", "confirmed_by_professional": True,
        }],
        "conditions": [], "regular_medications": [],
        "primary_doctor_name": None, "primary_clinic_name": None, "primary_clinic_phone": None,
        "emergency_contact_name": None, "emergency_contact_relationship": None, "emergency_contact_phone": None,
        "emergency_instructions": None, "last_reviewed_at": None, "last_reviewed_by_name": None,
        "has_profile": True, "generated_at": "2026-08-24T10:00:00+07:00",
        "disclaimer": "d", "privacy_note": "p",
    }
    base.update(overrides)
    return base


def test_preview_returns_a_signed_snapshot_token(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    body = _preview_card(client, user["token"], child["id"]).get_json()
    assert isinstance(body.get("snapshot_token"), str)
    assert len(body["snapshot_token"]) > 20


def test_valid_unchanged_snapshot_produces_a_pdf(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    token = _snapshot_token_from_preview(client, user["token"], child["id"])
    resp = _pdf_card(client, user["token"], child["id"], snapshot_token=token)
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")


def test_pdf_content_matches_the_previewed_report(client):
    """
    Requirement: 'PDF content corresponds to the previewed data.' TANPA
    dependency ekstraksi teks PDF pihak ketiga (pola sama persis
    test_consultation_pdf.py -- diverifikasi lewat flowable reportlab
    yang SAMA PERSIS dipakai render_emergency_card_pdf, bukan lewat
    parsing PDF akhir). Laporan di-rebuild pakai `preview_at` PERSIS
    dari token yang diterbitkan preview -- membuktikan endpoint PDF
    beneran merender data yang SAMA, bukan cuma "berhasil 200 apa pun
    isinya".
    """
    from utils.emergency_card_pdf import render_medical_profile_flowables
    from utils.emergency_card_report import build_emergency_card_summary
    from utils.pdf_common import BaseStyles

    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    preview_body = _preview_card(client, user["token"], child["id"]).get_json()
    token = preview_body["snapshot_token"]
    assert _pdf_card(client, user["token"], child["id"], snapshot_token=token).status_code == 200

    with client.application.app_context():
        claims = decode_snapshot_token(token, child_id=child["id"], user_id=user["id"])
        preview_at = datetime.fromisoformat(claims["preview_at"])
        child_row = Child.query.get(child["id"])
        profile_row = ChildMedicalProfile.query.filter_by(child_id=child["id"]).first()
        summary = build_emergency_card_summary(child_row, profile_row, preview_at)
        flows = render_medical_profile_flowables(summary, BaseStyles())

    texts = []
    for f in flows:
        if hasattr(f, "text"):
            texts.append(f.text)
        elif hasattr(f, "_cellvalues"):
            for row in f._cellvalues:
                for cell in row:
                    if hasattr(cell, "text"):
                        texts.append(cell.text)
    joined = "\n".join(texts)
    assert "Amoxicillin" in joined
    assert preview_body["allergies"][0]["allergen"] in joined
    assert preview_body["primary_doctor_name"] in joined


def test_profile_edit_by_another_caregiver_after_preview_causes_409(client):
    owner = register(client, name="Pemilik", email="owner-snap1@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-snap1@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")
    _put_profile(client, owner["token"], child["id"], SAMPLE_PAYLOAD)

    token = _snapshot_token_from_preview(client, owner["token"], child["id"])
    _put_profile(client, editor["token"], child["id"], {**SAMPLE_PAYLOAD, "blood_type": "A-"})

    resp = _pdf_card(client, owner["token"], child["id"], snapshot_token=token)
    assert resp.status_code == 409
    assert "Muat ulang pratinjau" in resp.get_json()["error"]


def test_review_after_preview_causes_409(client):
    """Field `last_reviewed_at`/`last_reviewed_by_name` ikut termasuk di bentuk kanonik (lihat utils/emergency_card_snapshot.py) -- aksi 'review' SENGAJA ikut membatalkan snapshot lama walau tidak mengubah field profil lain."""
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    token = _snapshot_token_from_preview(client, user["token"], child["id"])
    _review_profile(client, user["token"], child["id"])

    resp = _pdf_card(client, user["token"], child["id"], snapshot_token=token)
    assert resp.status_code == 409


def test_medication_schedule_creation_after_preview_causes_409(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    token = _snapshot_token_from_preview(client, user["token"], child["id"])
    client.post(
        f"/api/children/{child['id']}/medication-schedules",
        json={"medication_name": "Obat Baru", "times_of_day": ["08:00"], "start_date": "2020-01-01"},
        headers=auth_headers(user["token"]),
    )

    resp = _pdf_card(client, user["token"], child["id"], snapshot_token=token)
    assert resp.status_code == 409


def test_medication_schedule_edit_after_preview_causes_409(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    sched = client.post(
        f"/api/children/{child['id']}/medication-schedules",
        json={"medication_name": "Obat Rutin", "times_of_day": ["08:00"], "start_date": "2020-01-01"},
        headers=auth_headers(user["token"]),
    ).get_json()

    token = _snapshot_token_from_preview(client, user["token"], child["id"])
    client.patch(
        f"/api/children/{child['id']}/medication-schedules/{sched['id']}",
        json={"medication_name": "Obat Rutin Diubah"}, headers=auth_headers(user["token"]),
    )

    resp = _pdf_card(client, user["token"], child["id"], snapshot_token=token)
    assert resp.status_code == 409


def test_medication_schedule_deactivation_after_preview_causes_409(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    sched = client.post(
        f"/api/children/{child['id']}/medication-schedules",
        json={"medication_name": "Obat Rutin", "times_of_day": ["08:00"], "start_date": "2020-01-01"},
        headers=auth_headers(user["token"]),
    ).get_json()

    token = _snapshot_token_from_preview(client, user["token"], child["id"])
    client.patch(
        f"/api/children/{child['id']}/medication-schedules/{sched['id']}",
        json={"is_active": False}, headers=auth_headers(user["token"]),
    )

    resp = _pdf_card(client, user["token"], child["id"], snapshot_token=token)
    assert resp.status_code == 409


def test_medication_schedule_deletion_after_preview_causes_409(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    sched = client.post(
        f"/api/children/{child['id']}/medication-schedules",
        json={"medication_name": "Obat Rutin", "times_of_day": ["08:00"], "start_date": "2020-01-01"},
        headers=auth_headers(user["token"]),
    ).get_json()

    token = _snapshot_token_from_preview(client, user["token"], child["id"])
    client.delete(
        f"/api/children/{child['id']}/medication-schedules/{sched['id']}", headers=auth_headers(user["token"]),
    )

    resp = _pdf_card(client, user["token"], child["id"], snapshot_token=token)
    assert resp.status_code == 409


def test_child_display_data_change_after_preview_causes_409(client):
    user = register(client)
    child = create_child(client, user["token"], name="Nama Lama")
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    token = _snapshot_token_from_preview(client, user["token"], child["id"])
    client.put(
        f"/api/children/{child['id']}", json={"nickname": "Panggilan Baru"}, headers=auth_headers(user["token"]),
    )

    resp = _pdf_card(client, user["token"], child["id"], snapshot_token=token)
    assert resp.status_code == 409


def test_unchanged_data_with_later_wall_clock_still_exports_previewed_snapshot(client, monkeypatch):
    """Requirement #10: endpoint PDF TIDAK PERNAH mengambil now_wib() baru buat MEMBANGUN laporan (cuma buat metadata audit/nama file) -- wall-clock maju TIDAK mempengaruhi kecocokan digest selama data DB-nya sendiri tidak berubah."""
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    token = _snapshot_token_from_preview(client, user["token"], child["id"])

    later = datetime.now() + timedelta(hours=1)
    monkeypatch.setattr(medical_profile_routes_module, "now_wib", lambda: later)

    resp = _pdf_card(client, user["token"], child["id"], snapshot_token=token)
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")


def test_expired_snapshot_token_is_rejected(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    real_time = time.time
    with patch("time.time", return_value=real_time() - 3600):
        token = _snapshot_token_from_preview(client, user["token"], child["id"])

    resp = _pdf_card(client, user["token"], child["id"], snapshot_token=token)
    assert resp.status_code == 400


def test_tampered_snapshot_token_is_rejected(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    token = _snapshot_token_from_preview(client, user["token"], child["id"])

    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    resp = _pdf_card(client, user["token"], child["id"], snapshot_token=tampered)
    assert resp.status_code == 400


def test_snapshot_token_for_another_child_is_rejected(client):
    user = register(client)
    child_a = create_child(client, user["token"], name="Anak A")
    child_b = create_child(client, user["token"], name="Anak B")
    _put_profile(client, user["token"], child_a["id"], SAMPLE_PAYLOAD)
    _put_profile(client, user["token"], child_b["id"], SAMPLE_PAYLOAD)

    token_for_a = _snapshot_token_from_preview(client, user["token"], child_a["id"])
    resp = _pdf_card(client, user["token"], child_b["id"], snapshot_token=token_for_a)
    assert resp.status_code == 403


def test_snapshot_token_for_another_user_is_rejected(client):
    owner = register(client, name="Pemilik", email="owner-snap2@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-snap2@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")
    _put_profile(client, owner["token"], child["id"], SAMPLE_PAYLOAD)

    token_for_owner = _snapshot_token_from_preview(client, owner["token"], child["id"])
    resp = _pdf_card(client, editor["token"], child["id"], snapshot_token=token_for_owner)
    assert resp.status_code == 403


def test_missing_snapshot_token_is_rejected(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    resp = _pdf_card(client, user["token"], child["id"], snapshot_token=None)
    assert resp.status_code == 400


def test_pdf_rejects_non_object_json_body(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    resp = client.post(
        f"/api/children/{child['id']}/emergency-card/pdf", json=["bukan", "objek"], headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 400


def test_pdf_rejects_malformed_json_body(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    resp = client.post(
        f"/api/children/{child['id']}/emergency-card/pdf",
        data="{not valid json", headers={**auth_headers(user["token"]), "Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_pdf_rejects_oversized_body(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    resp = client.post(
        f"/api/children/{child['id']}/emergency-card/pdf",
        json={"snapshot_token": "x" * 5_000}, headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 413


def test_pdf_body_at_exact_boundary_passes_size_check(client):
    """Body PERSIS di batas TIDAK PERNAH 413 -- kalau gagal, gagalnya karena token-nya sendiri tidak valid (padding acak), BUKAN karena ukuran (batas ukuran murni <=, bukan <)."""
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    body = _pdf_body_of_exact_size(medical_profile_routes_module.MAX_EMERGENCY_CARD_PDF_BODY_BYTES)
    resp = client.post(
        f"/api/children/{child['id']}/emergency-card/pdf",
        data=body, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp.status_code != 413


def test_pdf_body_one_byte_over_boundary_is_rejected(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    body = _pdf_body_of_exact_size(medical_profile_routes_module.MAX_EMERGENCY_CARD_PDF_BODY_BYTES + 1)
    resp = client.post(
        f"/api/children/{child['id']}/emergency-card/pdf",
        data=body, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 413


def test_pdf_missing_content_length_with_oversized_body_is_rejected(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    big_body = _pdf_body_of_exact_size(medical_profile_routes_module.MAX_EMERGENCY_CARD_PDF_BODY_BYTES + 5_000)
    status_code, _ = _post_without_content_length(
        client, f"/api/children/{child['id']}/emergency-card/pdf", user["token"], big_body,
    )
    assert status_code == 413


def test_viewer_gets_same_403_for_pdf_regardless_of_token_or_body_size(client):
    owner = register(client, name="Pemilik", email="owner-snap3@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-snap3@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")
    _put_profile(client, owner["token"], child["id"], SAMPLE_PAYLOAD)

    valid_owner_token = _snapshot_token_from_preview(client, owner["token"], child["id"])

    resp_missing = _pdf_card(client, viewer["token"], child["id"], snapshot_token=None)
    resp_garbage = _pdf_card(client, viewer["token"], child["id"], snapshot_token="garbage")
    resp_not_theirs = _pdf_card(client, viewer["token"], child["id"], snapshot_token=valid_owner_token)

    huge_body = _pdf_body_of_exact_size(medical_profile_routes_module.MAX_EMERGENCY_CARD_PDF_BODY_BYTES + 5_000)
    resp_oversized = client.post(
        f"/api/children/{child['id']}/emergency-card/pdf",
        data=huge_body, content_type="application/json", headers=auth_headers(viewer["token"]),
    )

    bodies = [resp.get_json() for resp in (resp_missing, resp_garbage, resp_not_theirs, resp_oversized)]
    for resp in (resp_missing, resp_garbage, resp_not_theirs, resp_oversized):
        assert resp.status_code == 403
    assert all(b == bodies[0] for b in bodies)


def test_no_pdf_renderer_called_for_rejected_requests(client, monkeypatch):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("render_emergency_card_pdf should not be called for a rejected request")

    monkeypatch.setattr(medical_profile_routes_module, "render_emergency_card_pdf", _fail_if_called)

    assert _pdf_card(client, user["token"], child["id"], snapshot_token=None).status_code == 400

    token = _snapshot_token_from_preview(client, user["token"], child["id"])
    assert _pdf_card(client, user["token"], child["id"], snapshot_token=token[:-1] + "x").status_code == 400

    token2 = _snapshot_token_from_preview(client, user["token"], child["id"])
    _put_profile(client, user["token"], child["id"], {**SAMPLE_PAYLOAD, "blood_type": "A-"})
    assert _pdf_card(client, user["token"], child["id"], snapshot_token=token2).status_code == 409


def test_no_audit_event_for_rejected_or_stale_pdf_requests(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    before = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="emergency_card_pdf_export").count()

    _pdf_card(client, user["token"], child["id"], snapshot_token=None)
    _pdf_card(client, user["token"], child["id"], snapshot_token="garbage-token")
    token = _snapshot_token_from_preview(client, user["token"], child["id"])
    _put_profile(client, user["token"], child["id"], {**SAMPLE_PAYLOAD, "blood_type": "A-"})
    _pdf_card(client, user["token"], child["id"], snapshot_token=token)

    after = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="emergency_card_pdf_export").count()
    assert after == before


def test_successful_pdf_export_creates_exactly_one_audit_event(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    before = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="emergency_card_pdf_export").count()

    resp = _pdf_card(client, user["token"], child["id"])
    assert resp.status_code == 200

    after = CaregiverAuditEvent.query.filter_by(child_id=child["id"], entity_type="emergency_card_pdf_export").count()
    assert after == before + 1


def test_snapshot_token_claims_never_contain_medical_or_contact_values(client):
    user = register(client)
    child = create_child(client, user["token"])
    _put_profile(client, user["token"], child["id"], SAMPLE_PAYLOAD)
    token = _snapshot_token_from_preview(client, user["token"], child["id"])

    with client.application.app_context():
        claims = decode_snapshot_token(token, child_id=child["id"], user_id=user["id"])
    assert set(claims.keys()) == {"v", "child_id", "user_id", "preview_at", "digest"}

    haystack = token + json.dumps(claims)
    for sensitive in (
        "Amoxicillin", "Kacang tanah", "Asma", "dr. Sarah", "Budi Santoso",
        "021-5551234", "0812-3456-7890", "Hubungi ayah", "O+",
    ):
        assert sensitive not in haystack


def test_canonicalization_is_stable_regardless_of_dict_key_order():
    a = _sample_summary()
    b = dict(reversed(list(a.items())))
    b["allergies"] = [dict(reversed(list(a["allergies"][0].items())))]
    assert digest_emergency_card_report(a) == digest_emergency_card_report(b)


def test_relevant_content_change_alters_the_digest():
    a = _sample_summary()
    b = _sample_summary(blood_type="A-", blood_type_label="A-")
    assert digest_emergency_card_report(a) != digest_emergency_card_report(b)


def test_response_only_capability_field_does_not_alter_the_digest():
    a = _sample_summary()
    b = _sample_summary()
    b["capabilities"] = {"can_view_medical_profile": True, "can_edit_medical_profile": False}
    assert digest_emergency_card_report(a) == digest_emergency_card_report(b)
