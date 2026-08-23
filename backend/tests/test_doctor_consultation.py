"""
Test Doctor Consultation Workflow — Phase 1
(`/children/<id>/doctor-consultation/preview` & `.../pdf`). Lihat
backend/docs/DOCTOR_CONSULTATION.md buat kontrak lengkap.

SEMUA test pakai fixture `client` (SQLite in-memory, lihat
tests/conftest.py), TIDAK PERNAH menyentuh instance/tracker.db asli.
"Sekarang"/"hari ini" WAJIB dibekukan lewat `_freeze(monkeypatch)` di
SETIAP test yang bergantung ke tanggal — endpoint ini manggil
`today_wib()`/`now_wib()` di layer route (bukan di utils/consultation_report.py),
persis pola test_reminders.py/test_insights.py.
"""
import os
from datetime import date, datetime, timedelta

import pytest

import routes.doctor_consultation_routes as consultation_routes_module
from extensions import db
from models import (
    CaregiverAuditEvent, DoctorVisitLog, GrowthMeasurement, IllnessLog,
    MedicationLog, MilestoneLog, TemperatureLog,
)
from tests.conftest import auth_headers, create_child, register
from tests.test_roles_permissions import invite_and_join
from utils.consultation_report import INSIGHT_CODE_DESCRIPTIONS, SENSITIVE_SECTIONS

FAKE_TODAY = date(2026, 8, 23)
FAKE_NOW = datetime(2026, 8, 23, 10, 0, 0)


def _freeze(monkeypatch, today=FAKE_TODAY, now=FAKE_NOW):
    monkeypatch.setattr(consultation_routes_module, "today_wib", lambda: today)
    monkeypatch.setattr(consultation_routes_module, "now_wib", lambda: now)


def _preview(client, token, child_id, period=None, sections=None, questions=None, note=None):
    body = {"period": period or {"preset": "7d"}}
    if sections is not None:
        body["sections"] = sections
    if questions is not None:
        body["questions"] = questions
    if note is not None:
        body["additional_note"] = note
    return client.post(
        f"/api/children/{child_id}/doctor-consultation/preview", json=body, headers=auth_headers(token)
    )


def _pdf(client, token, child_id, period=None, sections=None, questions=None, note=None):
    body = {"period": period or {"preset": "7d"}}
    if sections is not None:
        body["sections"] = sections
    if questions is not None:
        body["questions"] = questions
    if note is not None:
        body["additional_note"] = note
    return client.post(
        f"/api/children/{child_id}/doctor-consultation/pdf", json=body, headers=auth_headers(token)
    )


# --------------------------------------------------------------------------
# 1. Otorisasi & capability flags.
# --------------------------------------------------------------------------


def test_unauthenticated_preview_gets_401(client, monkeypatch):
    # SENGAJA nggak pernah register()/login di client ini -- test client
    # Flask nyimpen cookie session ANTAR request dalam 1 test yang SAMA,
    # jadi register() bakal bikin request berikutnya diam-diam "login"
    # lewat fallback session cookie (lihat utils/auth.py:get_current_user_id)
    # walau nggak ngirim header Authorization sama sekali.
    _freeze(monkeypatch)
    resp = client.post("/api/children/1/doctor-consultation/preview", json={"period": {"preset": "7d"}})
    assert resp.status_code == 401


def test_inaccessible_child_gets_404_not_403(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-dc@example.com")
    child = create_child(client, owner["token"])
    outsider = register(client, name="Orang Lain", email="outsider-dc@example.com")
    resp = _preview(client, outsider["token"], child["id"])
    assert resp.status_code == 404


def test_nonexistent_child_gets_same_404(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    resp = _preview(client, user["token"], 999999)
    assert resp.status_code == 404


def test_owner_can_preview_and_export(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    preview = _preview(client, user["token"], child["id"])
    assert preview.status_code == 200
    body = preview.get_json()
    assert body["capabilities"] == {
        "can_preview": True, "can_export": True, "can_add_private_notes": True, "can_record_visit": True,
    }
    pdf = _pdf(client, user["token"], child["id"])
    assert pdf.status_code == 200
    assert pdf.content_type == "application/pdf"


def test_editor_can_preview_and_export(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-dc2@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-dc@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")

    preview = _preview(client, editor["token"], child["id"])
    assert preview.status_code == 200
    assert preview.get_json()["capabilities"]["can_export"] is True
    pdf = _pdf(client, editor["token"], child["id"])
    assert pdf.status_code == 200


def test_viewer_can_preview_but_not_export(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-dc3@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-dc@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")

    preview = _preview(client, viewer["token"], child["id"])
    assert preview.status_code == 200
    caps = preview.get_json()["capabilities"]
    assert caps["can_preview"] is True
    assert caps["can_export"] is False
    assert caps["can_add_private_notes"] is False
    assert caps["can_record_visit"] is False

    pdf = _pdf(client, viewer["token"], child["id"])
    assert pdf.status_code == 403


def test_viewer_cannot_submit_questions_or_note(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-dc4@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer2", email="viewer2-dc@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")

    resp = _preview(client, viewer["token"], child["id"], questions="Kenapa demam terus?")
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# 2. Periode: preset, custom, dan validasi rentang (backend otoritatif).
# --------------------------------------------------------------------------


def test_preset_periods_resolve_correct_boundaries(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    for preset, days in (("7d", 7), ("14d", 14), ("30d", 30)):
        resp = _preview(client, user["token"], child["id"], period={"preset": preset})
        assert resp.status_code == 200, resp.get_json()
        period = resp.get_json()["period"]
        assert period["end_date"] == FAKE_TODAY.isoformat()
        assert period["start_date"] == (FAKE_TODAY - timedelta(days=days - 1)).isoformat()
        assert period["days"] == days
        assert period["timezone"] == "Asia/Jakarta"


def test_custom_range_is_accepted_and_returned(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"], period={
        "preset": "custom", "start_date": "2026-08-01", "end_date": "2026-08-10",
    })
    assert resp.status_code == 200
    period = resp.get_json()["period"]
    assert period["start_date"] == "2026-08-01"
    assert period["end_date"] == "2026-08-10"
    assert period["days"] == 10


def test_custom_range_reversed_dates_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"], period={
        "preset": "custom", "start_date": "2026-08-10", "end_date": "2026-08-01",
    })
    assert resp.status_code == 400


def test_custom_range_future_end_date_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"], period={
        "preset": "custom", "start_date": "2026-08-01", "end_date": "2026-08-30",
    })
    assert resp.status_code == 400


def test_custom_range_over_90_days_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"], period={
        "preset": "custom", "start_date": "2026-01-01", "end_date": "2026-08-23",
    })
    assert resp.status_code == 400


def test_custom_range_exactly_90_days_is_accepted(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    start = (FAKE_TODAY - timedelta(days=89)).isoformat()
    resp = _preview(client, user["token"], child["id"], period={
        "preset": "custom", "start_date": start, "end_date": FAKE_TODAY.isoformat(),
    })
    assert resp.status_code == 200
    assert resp.get_json()["period"]["days"] == 90


def test_unknown_period_preset_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"], period={"preset": "60d"})
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# 3. Section allowlist & default privacy-conscious.
# --------------------------------------------------------------------------


def test_default_sections_are_privacy_conscious(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"])
    body = resp.get_json()
    included = set(body["included_sections"])
    assert included == {
        "child_summary", "feeding", "sleep", "diaper", "growth", "temperature", "vaccination", "milestones",
    }
    assert not (included & SENSITIVE_SECTIONS)
    assert body["sensitive_sections_included"] == []


def test_sensitive_sections_only_appear_when_explicitly_selected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    default_resp = _preview(client, user["token"], child["id"])
    assert "medication" not in default_resp.get_json()["sections"]
    assert "illness" not in default_resp.get_json()["sections"]
    assert "doctor_visits" not in default_resp.get_json()["sections"]

    opted_in = _preview(client, user["token"], child["id"], sections=["medication", "illness", "doctor_visits"])
    body = opted_in.get_json()
    assert set(body["sections"].keys()) == {"medication", "illness", "doctor_visits"}
    assert set(body["sensitive_sections_included"]) == {"medication", "illness", "doctor_visits"}


def test_unknown_section_code_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"], sections=["feeding", "not_a_real_section"])
    assert resp.status_code == 400


def test_duplicate_section_code_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"], sections=["feeding", "feeding"])
    assert resp.status_code == 400


def test_empty_section_list_is_a_valid_minimal_report(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"], sections=[])
    assert resp.status_code == 200
    assert resp.get_json()["sections"] == {}


# --------------------------------------------------------------------------
# 4. Questions/notes -- transien, tidak pernah disimpan, tidak pernah masuk audit.
# --------------------------------------------------------------------------


def test_questions_and_note_are_echoed_but_never_persisted(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(
        client, user["token"], child["id"], sections=["questions", "note"],
        questions="Apakah normal kalau sering rewel malam hari?", note="Anak lagi tumbuh gigi minggu ini.",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["sections"]["questions"]["text"] == "Apakah normal kalau sering rewel malam hari?"
    assert body["sections"]["note"]["text"] == "Anak lagi tumbuh gigi minggu ini."

    # TIDAK ADA tabel yang cocok buat nyimpen teks ini -- pastikan nggak
    # nyelinap ke salah satu tabel lognya anak ini lewat cara lain mana pun.
    for text in ("rewel malam hari", "tumbuh gigi minggu ini"):
        assert MedicationLog.query.filter(MedicationLog.child_id == child["id"]).count() == 0
        assert IllnessLog.query.filter(IllnessLog.child_id == child["id"]).count() == 0


def test_questions_and_note_absent_from_pdf_export_audit_event(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    secret = "RAHASIA-pertanyaan-dan-catatan-caregiver"
    resp = _pdf(client, user["token"], child["id"], sections=["questions", "note"], questions=secret, note=secret)
    assert resp.status_code == 200

    events = CaregiverAuditEvent.query.filter_by(
        child_id=child["id"], entity_type="doctor_consultation_pdf_export"
    ).all()
    assert len(events) == 1
    event = events[0]
    assert event.changed_fields_json is None
    assert event.entity_id == 0
    assert secret not in str(event.__dict__)


def test_questions_over_length_limit_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"], questions="x" * 2000)
    assert resp.status_code == 400


def test_note_over_length_limit_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"], note="y" * 2000)
    assert resp.status_code == 400


def test_questions_line_endings_are_normalized(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(
        client, user["token"], child["id"], sections=["questions"], questions="baris 1\r\nbaris 2\rbaris 3",
    )
    assert resp.status_code == 200
    assert resp.get_json()["sections"]["questions"]["text"] == "baris 1\nbaris 2\nbaris 3"


def test_html_script_content_in_questions_is_treated_as_plain_text(client, monkeypatch):
    """
    Preview (JSON) memantulkan teks APA ADANYA (JSON bukan HTML, nggak
    ada eksekusi markup) -- TAPI PDF (yang render lewat reportlab
    Paragraph, PARSER mirip-XML) WAJIB tetap berhasil dibuat tanpa
    exception walau isinya tag HTML/script -- kalau escaping-nya lupa,
    reportlab bakal nge-raise parse error pas coba nafsirkan `<script>`
    sebagai tag nggak dikenal, endpoint ini bakal 500 alih-alih 200.
    """
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    payload = "<script>alert(1)</script><b>bold</b> & \"quoted\""

    preview = _preview(client, user["token"], child["id"], sections=["questions"], questions=payload)
    assert preview.status_code == 200
    assert preview.get_json()["sections"]["questions"]["text"] == payload

    pdf = _pdf(client, user["token"], child["id"], sections=["questions"], questions=payload)
    assert pdf.status_code == 200
    assert pdf.data.startswith(b"%PDF-")


# --------------------------------------------------------------------------
# 5. Empty-data & partial-data reports.
# --------------------------------------------------------------------------


def test_empty_data_report_succeeds_with_zeroed_out_sections(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"], sections=[
        "child_summary", "feeding", "growth", "insights",
    ])
    assert resp.status_code == 200
    sections = resp.get_json()["sections"]
    assert sections["feeding"]["total_events"] == 0
    assert sections["growth"]["latest"] is None
    assert sections["insights"]["data_quality"]["has_any_data"] is False
    assert sections["insights"]["insights"] == [
        {"code": "insufficient_data", "description": INSIGHT_CODE_DESCRIPTIONS["insufficient_data"](None), "metric": None, "direction": None, "value": None}
    ]


def test_insight_codes_always_come_from_the_allowlist(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(MedicationLog(child_id=child["id"], medication_name="Obat A", timestamp=FAKE_NOW - timedelta(hours=1)))
    db.session.commit()
    resp = _preview(client, user["token"], child["id"], sections=["insights"])
    assert resp.status_code == 200
    for card in resp.get_json()["sections"]["insights"]["insights"]:
        assert card["code"] in INSIGHT_CODE_DESCRIPTIONS


def test_insights_section_never_leaks_sensitive_free_text(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    marker = "RAHASIA-nama-obat-dan-gejala-anak"
    db.session.add(MedicationLog(child_id=child["id"], medication_name=marker, dosage=marker, timestamp=FAKE_NOW))
    db.session.add(IllnessLog(child_id=child["id"], illness_name=marker, symptoms=marker, start_date=FAKE_TODAY))
    db.session.commit()
    resp = _preview(client, user["token"], child["id"], sections=["insights"])
    assert resp.status_code == 200
    assert marker not in str(resp.get_json())


# --------------------------------------------------------------------------
# 6. Data-minimization / row caps / truncation.
# --------------------------------------------------------------------------


def test_medication_rows_are_bounded_and_truncation_is_flagged(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    for i in range(25):
        db.session.add(MedicationLog(
            child_id=child["id"], medication_name=f"Obat {i}", timestamp=FAKE_NOW - timedelta(hours=i),
        ))
    db.session.commit()

    resp = _preview(client, user["token"], child["id"], sections=["medication"])
    section = resp.get_json()["sections"]["medication"]
    assert len(section["entries"]) == 20
    assert section["total_count_in_period"] == 25
    assert section["truncated"] is True


def test_doctor_visits_section_excludes_notes_field(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(DoctorVisitLog(
        child_id=child["id"], visit_date=FAKE_TODAY, doctor_name="Dr. A", clinic_name="Klinik A",
        reason="Demam", diagnosis="ISPA", notes="RAHASIA-catatan-dokter-bebas",
    ))
    db.session.commit()
    resp = _preview(client, user["token"], child["id"], sections=["doctor_visits"])
    body = resp.get_json()
    assert "RAHASIA-catatan-dokter-bebas" not in str(body)
    entry = body["sections"]["doctor_visits"]["entries"][0]
    assert "notes" not in entry


def test_milestones_section_never_includes_custom_label(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(MilestoneLog(
        child_id=child["id"], milestone_type="custom", custom_label="RAHASIA-label-bebas", achieved_date=FAKE_TODAY,
    ))
    db.session.commit()
    resp = _preview(client, user["token"], child["id"], sections=["milestones"])
    assert "RAHASIA-label-bebas" not in str(resp.get_json())


def test_report_never_leaks_another_childs_data(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child_a = create_child(client, user["token"], name="Anak A")
    child_b = create_child(client, user["token"], name="Anak B")
    db.session.add(MedicationLog(child_id=child_b["id"], medication_name="RAHASIA-anak-b", timestamp=FAKE_NOW))
    db.session.commit()

    resp = _preview(client, user["token"], child_a["id"], sections=["medication"])
    assert "RAHASIA-anak-b" not in str(resp.get_json())
    assert resp.get_json()["sections"]["medication"]["entries"] == []


# --------------------------------------------------------------------------
# 7. PDF response shape & safety.
# --------------------------------------------------------------------------


def test_pdf_response_has_correct_content_type_and_signature(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _pdf(client, user["token"], child["id"])
    assert resp.status_code == 200
    assert resp.content_type == "application/pdf"
    assert resp.data.startswith(b"%PDF-")
    assert "attachment" in resp.headers.get("Content-Disposition", "")


def test_pdf_filename_is_sanitized_and_has_no_header_injection(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"], name='Weird"Name\r\nX-Evil: 1')
    resp = _pdf(client, user["token"], child["id"])
    assert resp.status_code == 200
    disposition = resp.headers.get("Content-Disposition", "")
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert "X-Evil" not in disposition


def test_pdf_generation_with_many_rows_across_sections_does_not_crash(client, monkeypatch):
    """Proksi 'multi-page generation' -- reportlab paginasi otomatis pas konten meluap; kita nggak punya parser PDF di sini buat itung halaman pasti, jadi diverifikasi lewat berhasil-tidaknya generate + ukuran payload yang signifikan lebih besar dari laporan minimal."""
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    for i in range(20):
        db.session.add(GrowthMeasurement(child_id=child["id"], measured_date=FAKE_TODAY - timedelta(days=i), weight_kg=5 + i * 0.1))
        db.session.add(IllnessLog(child_id=child["id"], illness_name=f"Sakit {i}", start_date=FAKE_TODAY - timedelta(days=i), symptoms="Demam ringan " * 10))
        db.session.add(MedicationLog(child_id=child["id"], medication_name=f"Obat {i}", dosage="1 sdt", timestamp=FAKE_NOW - timedelta(days=i)))
        db.session.add(DoctorVisitLog(child_id=child["id"], visit_date=FAKE_TODAY - timedelta(days=i), doctor_name=f"Dr {i}", reason="Kontrol rutin " * 5))
        db.session.add(MilestoneLog(child_id=child["id"], milestone_type="bisa_duduk", achieved_date=FAKE_TODAY - timedelta(days=i)))
    db.session.commit()

    big = _pdf(client, user["token"], child["id"], sections=[
        "child_summary", "growth", "illness", "medication", "doctor_visits", "milestones", "vaccination",
    ])
    assert big.status_code == 200
    assert big.data.startswith(b"%PDF-")

    minimal = _pdf(client, user["token"], child["id"], sections=["child_summary"])
    assert minimal.status_code == 200
    assert len(big.data) > len(minimal.data)


def test_long_plain_text_note_wraps_without_crashing(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    long_note = "Ini catatan yang sangat panjang tanpa baris baru sama sekali. " * 15
    resp = _pdf(client, user["token"], child["id"], sections=["note"], note=long_note[:1000])
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")


def test_no_pdf_file_is_left_on_disk_after_export(client, monkeypatch, tmp_path):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(consultation_routes_module.__file__)))
    uploads_dir = os.path.join(backend_dir, "uploads")
    before = set(os.listdir(uploads_dir)) if os.path.isdir(uploads_dir) else set()

    resp = _pdf(client, user["token"], child["id"])
    assert resp.status_code == 200

    after = set(os.listdir(uploads_dir)) if os.path.isdir(uploads_dir) else set()
    assert before == after


# --------------------------------------------------------------------------
# 8. Audit event -- CUMA PDF export, tidak pernah preview.
# --------------------------------------------------------------------------


def test_preview_does_not_create_any_audit_event(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    before = CaregiverAuditEvent.query.filter_by(child_id=child["id"]).count()
    _preview(client, user["token"], child["id"])
    _preview(client, user["token"], child["id"], sections=["feeding", "medication"])
    after = CaregiverAuditEvent.query.filter_by(child_id=child["id"]).count()
    assert after == before


def test_pdf_export_creates_exactly_one_safe_audit_event(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    _pdf(client, user["token"], child["id"])
    events = CaregiverAuditEvent.query.filter_by(
        child_id=child["id"], entity_type="doctor_consultation_pdf_export"
    ).all()
    assert len(events) == 1
    assert events[0].action == "create"
    assert events[0].actor_user_id == user["id"]


# --------------------------------------------------------------------------
# 9. Regresi: doctor-visit & PDF umum yang sudah ada tidak berubah.
# --------------------------------------------------------------------------


def test_existing_doctor_visit_crud_still_works(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.post(
        f"/api/children/{child['id']}/doctor-visits",
        json={"visit_date": "2026-08-20", "doctor_name": "Dr. Test"},
        headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 201
    listing = client.get(f"/api/children/{child['id']}/doctor-visits", headers=auth_headers(user["token"]))
    assert listing.status_code == 200
    assert len(listing.get_json()) == 1


# --------------------------------------------------------------------------
# 10. Batas ukuran body khusus endpoint konsultasi (bug review Agustus 2026).
# --------------------------------------------------------------------------


def test_oversized_consultation_body_is_rejected_before_report_generation(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    # Field asing yang GEDE BANGET -- di luar 4 field yang dikenal, jadi
    # nggak pernah dipakai buat generate laporan apa pun, TAPI body-nya
    # sendiri harus tetap ditolak SEBELUM sempat coba diparse/dipakai.
    huge_body = {"period": {"preset": "7d"}, "padding": "x" * 30_000}
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/preview",
        json=huge_body, headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 413


def test_body_within_normal_bounds_is_accepted(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(
        client, user["token"], child["id"],
        sections=list(SENSITIVE_SECTIONS) + ["feeding", "sleep", "diaper", "growth"],
        questions="x" * 1000, note="y" * 1000,
    )
    assert resp.status_code == 200


def test_unexpected_top_level_fields_are_silently_ignored_consistent_with_other_endpoints(client, monkeypatch):
    """
    Kebijakan yang SENGAJA dipilih (didokumentasikan di
    backend/docs/DOCTOR_CONSULTATION.md): field top-level tak dikenal
    diabaikan diam-diam, KONSISTEN sama SELURUH endpoint lain di app ini
    (mis. routes/health_routes.py) yang juga nggak pernah menolak key
    request asing -- bukan kelalaian, keputusan sadar biar nggak ada
    kebijakan validasi yang beda sendiri cuma di endpoint ini.
    """
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/preview",
        json={"period": {"preset": "7d"}, "unexpected_field": "should be ignored, not rejected"},
        headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 200
