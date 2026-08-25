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
import json
import os
import time
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from werkzeug.test import EnvironBuilder

import routes.doctor_consultation_routes as consultation_routes_module
import routes.medication_schedule_routes as medication_schedule_routes_module
from extensions import db
from models import (
    CaregiverAuditEvent, DoctorVisitLog, GrowthMeasurement, IllnessLog,
    MedicationLog, MilestoneLog, TemperatureLog,
)
from tests.conftest import auth_headers, create_child, register
from tests.test_roles_permissions import invite_and_join
from utils.consultation_report import (
    INSIGHT_CODE_DESCRIPTIONS, MAX_CONSULTATION_BODY_BYTES, SENSITIVE_SECTIONS,
)
from utils.consultation_snapshot import decode_consultation_snapshot_token, digest_consultation_report

FAKE_TODAY = date(2026, 8, 23)
FAKE_NOW = datetime(2026, 8, 23, 10, 0, 0)


def _freeze(monkeypatch, today=FAKE_TODAY, now=FAKE_NOW):
    monkeypatch.setattr(consultation_routes_module, "today_wib", lambda: today)
    monkeypatch.setattr(consultation_routes_module, "now_wib", lambda: now)


def _freeze_medication_schedule(monkeypatch, now=FAKE_NOW):
    """Beku juga `now_wib()` di routes/medication_schedule_routes.py -- dipakai test yang bikin jadwal/aksi lewat endpoint itu SEBELUM preview konsultasi, biar 'sekarang' konsisten di kedua endpoint."""
    monkeypatch.setattr(medication_schedule_routes_module, "now_wib", lambda: now)


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


def _tamper_token(token):
    """
    Rusak tanda tangan token SECARA ANDAL -- ganti karakter PERTAMA
    segmen TANDA TANGAN (bagian setelah "." terakhir), BUKAN karakter
    TERAKHIR token secara keseluruhan. Base64url TANPA padding
    (dipakai itsdangerous) kadang menyisakan beberapa bit "kosong" di
    posisi karakter PALING AKHIR sebuah string -- mengganti karakter di
    posisi itu TIDAK SELALU mengubah byte hasil decode (flaky,
    ditemukan langsung: pernah lolos verifikasi tanda tangan di 1 dari
    banyak run test suite penuh). Karakter PERTAMA segmen tanda tangan
    TIDAK PERNAH berada di posisi bit sisa semacam itu -- penggantian
    di situ SELALU mengubah byte HMAC hasil decode.
    """
    head, sig = token.rsplit(".", 1)
    mutated_sig = ("a" if sig[0] != "a" else "b") + sig[1:]
    return f"{head}.{mutated_sig}"


_AUTO_TOKEN = object()  # sentinel: "belum dikasih eksplisit -- ambil token segar dari preview yang MATCHING"


def _pdf(client, token, child_id, period=None, sections=None, questions=None, note=None, snapshot_token=_AUTO_TOKEN):
    """
    Kalau `snapshot_token` TIDAK dikasih eksplisit, ambil token SEGAR
    dulu lewat `_preview` memakai period/sections/questions/note yang
    SAMA PERSIS (dan `token` user yang sama) -- kasus umum buat test
    yang cuma mau membuktikan alur PDF berhasil BIASA, tanpa perlu
    mengulang boilerplate preview->token di puluhan test yang sudah ada
    (persis pola tests/test_medical_profile.py:_pdf_card). Test yang
    mau menguji token itu SENDIRI (hilang/salah/kedaluwarsa/anak lain/
    user lain/laporan basi) mengirim `snapshot_token` eksplisit --
    termasuk `None` buat kasus "field tidak dikirim sama sekali"
    (backend memperlakukan field absen & `null` SAMA PERSIS lewat
    `data.get(...)`).
    """
    body = {"period": period or {"preset": "7d"}}
    if sections is not None:
        body["sections"] = sections
    if questions is not None:
        body["questions"] = questions
    if note is not None:
        body["additional_note"] = note
    if snapshot_token is _AUTO_TOKEN:
        preview_resp = _preview(client, token, child_id, period=period, sections=sections, questions=questions, note=note)
        snapshot_token = (preview_resp.get_json() or {}).get("snapshot_token")
    body["snapshot_token"] = snapshot_token
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
        # Child Medical Profile & Emergency Card Phase 1 -- kapabilitas
        # baru, Owner/Editor sama-sama True (lihat test_medical_profile.py
        # buat kontrak lengkap Viewer=False-nya).
        "can_include_medical_profile": True,
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


# --------------------------------------------------------------------------
# Integrasi Medication Schedule & Adherence Phase 1 -- ringkasan kepatuhan
# di dalam section `medication` yang SUDAH ADA (lihat
# backend/docs/MEDICATION_SCHEDULE.md dan
# utils/consultation_report.py:_medication_adherence_summary).
# --------------------------------------------------------------------------


def test_medication_section_adherence_summary_is_none_when_no_schedules_exist(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    resp = _preview(client, user["token"], child["id"], sections=["medication"])
    section = resp.get_json()["sections"]["medication"]
    assert section["adherence_summary"] is None


def test_medication_section_includes_adherence_summary_when_schedule_exists(client, monkeypatch):
    _freeze(monkeypatch)
    _freeze_medication_schedule(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    create_resp = client.post(
        f"/api/children/{child['id']}/medication-schedules",
        json={
            "medication_name": "Amoxicillin", "dose_value": 5, "dose_unit": "ml",
            "times_of_day": ["08:00"], "start_date": (FAKE_TODAY - timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(user["token"]),
    )
    assert create_resp.status_code == 201, create_resp.get_json()
    schedule_id = create_resp.get_json()["id"]
    occ_key = f"{FAKE_TODAY.isoformat()}T08:00"
    act_resp = client.post(
        f"/api/children/{child['id']}/medication-schedules/{schedule_id}/occurrences/{occ_key}/administer",
        json={}, headers=auth_headers(user["token"]),
    )
    assert act_resp.status_code == 201, act_resp.get_json()

    resp = _preview(client, user["token"], child["id"], sections=["medication"])
    summary = resp.get_json()["sections"]["medication"]["adherence_summary"]
    assert summary is not None
    assert summary["schedule_count"] == 1
    assert summary["expected_count"] == 2  # kemarin 08:00 (overdue) + hari ini 08:00 (administered)
    assert summary["administered_count"] == 1
    assert summary["overdue_unresolved_count"] == 1
    assert summary["adherence_percentage"] is not None
    # Ringkasan CUMA angka agregat -- TIDAK PERNAH nama obat/instruksi
    # per-jadwal (beda dari `entries`, yang MEMANG sudah menampilkan
    # medication_name sejak Phase 1 sebelumnya).
    assert "medication_name" not in summary
    assert "instructions" not in summary


def test_medication_adherence_summary_absent_when_medication_section_not_selected(client, monkeypatch):
    _freeze(monkeypatch)
    _freeze_medication_schedule(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    client.post(
        f"/api/children/{child['id']}/medication-schedules",
        json={"medication_name": "RAHASIA_Obat", "times_of_day": ["08:00"], "start_date": FAKE_TODAY.isoformat()},
        headers=auth_headers(user["token"]),
    )

    resp = _preview(client, user["token"], child["id"], sections=["feeding"])
    body = resp.get_json()
    assert "medication" not in body["sections"]
    assert "RAHASIA_Obat" not in json.dumps(body)


def test_medication_adherence_summary_present_in_pdf_export_too(client, monkeypatch):
    """Requirement: preview & PDF TETAP logically aligned -- section builder yang SAMA dipanggil dua-duanya, ringkasan kepatuhan otomatis ikut ke PDF tanpa perubahan terpisah di sana."""
    _freeze(monkeypatch)
    _freeze_medication_schedule(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    client.post(
        f"/api/children/{child['id']}/medication-schedules",
        json={"medication_name": "Amoxicillin", "times_of_day": ["08:00"], "start_date": FAKE_TODAY.isoformat()},
        headers=auth_headers(user["token"]),
    )
    resp = _pdf(client, user["token"], child["id"], sections=["medication"])
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")


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


# --------------------------------------------------------------------------
# 11. Bypass ukuran body lewat Content-Length yang hilang/chunked (bug
# review Agustus 2026) -- lihat backend/docs/DOCTOR_CONSULTATION.md
# bagian "Request validation & size limits" buat penjelasan lengkap.
# --------------------------------------------------------------------------


def _json_body_of_exact_size(target_bytes, extra=None):
    """
    Body JSON VALID {"period": {...}, ..., "padding": "xxx"} yang
    di-encode UTF-8 PERSIS `target_bytes` byte -- `padding` sengaja
    field TAK DIKENAL (diabaikan endpoint, lihat test kebijakan di
    atas) biar bisa dipakai ngatur ukuran body TANPA kesenggol
    validator panjang questions/note (1000 karakter) yang jalan
    BELAKANGAN, SETELAH lapis ukuran ini.
    """
    base = {"period": {"preset": "7d"}}
    if extra:
        base.update(extra)
    base["padding"] = ""
    base_len = len(json.dumps(base).encode("utf-8"))
    pad_len = target_bytes - base_len
    assert pad_len >= 0, f"target_bytes {target_bytes} terlalu kecil buat base payload ({base_len} byte)"
    base["padding"] = "x" * pad_len
    body = json.dumps(base).encode("utf-8")
    assert len(body) == target_bytes, (len(body), target_bytes)
    return body


def _post_without_content_length(client, path, token, body_bytes):
    """
    Bangun environ WSGI ASLI TANPA header Content-Length sama sekali
    (mensimulasikan request chunked/transfer tanpa panjang terdeklarasi)
    -- BUKAN cuma nyoba `content_length=None` ke test client biasa,
    yang diam-diam DIHITUNG ULANG dari `data=` yang dikasih
    (`EnvironBuilder.get_environ()`, lihat werkzeug/test.py) dan bakal
    bikin test ini LOLOS PALSU (kayak nggak ngetes apa-apa). Environ
    dibangun sekali lewat `EnvironBuilder` (buat header/auth/method yang
    benar), lalu `CONTENT_LENGTH` DIHAPUS MANUAL dan `wsgi.input_terminated`
    DIPASANG MANUAL (server yang declare dia sendiri yang nge-terminate
    stream-nya, mis. chunked -- lihat werkzeug/wsgi.py:get_input_stream)
    SEBELUM di-dispatch LANGSUNG lewat `app.wsgi_app` (BUKAN lewat
    `client.post`, yang bakal nge-reset environ ini lewat jalur
    EnvironBuilder yang sama lagi).
    """
    app = client.application
    builder = EnvironBuilder(
        path=path, method="POST", data=body_bytes, content_type="application/json",
        headers=auth_headers(token),
    )
    environ = builder.get_environ()
    assert "CONTENT_LENGTH" in environ  # EnvironBuilder emang ngitung otomatis -- makanya HARUS dihapus manual di bawah
    del environ["CONTENT_LENGTH"]
    environ["wsgi.input_terminated"] = True

    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status_code"] = int(status.split(" ", 1)[0])

    body_iter = app.wsgi_app(environ, start_response)
    response_body = b"".join(body_iter)
    return captured["status_code"], response_body


def test_request_content_length_is_genuinely_none_for_the_missing_content_length_helper(client, monkeypatch):
    """
    Verifikasi LANGSUNG (bukan diasumsikan) bahwa teknik simulasi di
    `_post_without_content_length` beneran bikin `request.content_length
    is None` di dalam request path -- push request context manual
    dengan environ yang SAMA (Content-Length dihapus) dan cek atribut
    ini SEBELUM view function mana pun jalan.
    """
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    app = client.application
    builder = EnvironBuilder(
        path=f"/api/children/{child['id']}/doctor-consultation/preview", method="POST",
        data=b'{"period": {"preset": "7d"}}', content_type="application/json",
        headers=auth_headers(user["token"]),
    )
    environ = builder.get_environ()
    del environ["CONTENT_LENGTH"]
    environ["wsgi.input_terminated"] = True

    with app.test_request_context(environ_overrides=environ):
        from flask import request
        assert request.content_length is None


def test_declared_content_length_over_limit_is_rejected_before_report_and_pdf_code_runs(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    def _fail_if_called(name):
        def _inner(*args, **kwargs):
            raise AssertionError(f"{name} should not be called for an oversized request")
        return _inner

    monkeypatch.setattr(consultation_routes_module, "build_consultation_report", _fail_if_called("build_consultation_report"))
    monkeypatch.setattr(consultation_routes_module, "render_consultation_pdf", _fail_if_called("render_consultation_pdf"))
    monkeypatch.setattr(consultation_routes_module, "record_audit_event", _fail_if_called("record_audit_event"))

    big_body = _json_body_of_exact_size(MAX_CONSULTATION_BODY_BYTES + 5_000)
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/preview",
        data=big_body, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 413
    assert resp.get_json() == {"error": "Ukuran permintaan terlalu besar"}
    assert CaregiverAuditEvent.query.filter_by(child_id=child["id"]).count() == 0


def test_missing_content_length_with_oversized_actual_body_is_rejected(client, monkeypatch):
    """
    INI defect yang lagi diperbaiki: request TANPA Content-Length yang
    body ASLINYA lebih dari MAX_CONSULTATION_BODY_BYTES WAJIB tetap
    ditolak 413 -- sebelumnya lolos lewat begitu saja sampai batas
    global 6MB.
    """
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    def _fail_if_called(name):
        def _inner(*args, **kwargs):
            raise AssertionError(f"{name} should not be called for an oversized request")
        return _inner

    monkeypatch.setattr(consultation_routes_module, "build_consultation_report", _fail_if_called("build_consultation_report"))
    monkeypatch.setattr(consultation_routes_module, "render_consultation_pdf", _fail_if_called("render_consultation_pdf"))
    monkeypatch.setattr(consultation_routes_module, "record_audit_event", _fail_if_called("record_audit_event"))

    big_body = _json_body_of_exact_size(MAX_CONSULTATION_BODY_BYTES + 5_000)
    status_code, body = _post_without_content_length(
        client, f"/api/children/{child['id']}/doctor-consultation/preview", user["token"], big_body,
    )
    assert status_code == 413
    assert json.loads(body) == {"error": "Ukuran permintaan terlalu besar"}
    assert CaregiverAuditEvent.query.filter_by(child_id=child["id"]).count() == 0


def test_missing_content_length_with_body_at_accepted_boundary_proceeds_normally(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    body = _json_body_of_exact_size(MAX_CONSULTATION_BODY_BYTES)
    status_code, body_out = _post_without_content_length(
        client, f"/api/children/{child['id']}/doctor-consultation/preview", user["token"], body,
    )
    assert status_code == 200
    assert json.loads(body_out)["period"]["start_date"]


def test_actual_body_exactly_at_limit_is_accepted(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    body = _json_body_of_exact_size(MAX_CONSULTATION_BODY_BYTES)
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/preview",
        data=body, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 200


def test_actual_body_one_byte_over_limit_is_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    body = _json_body_of_exact_size(MAX_CONSULTATION_BODY_BYTES + 1)
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/preview",
        data=body, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 413


def test_declared_and_actual_length_within_bounds_still_works_normally(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"])
    assert resp.status_code == 200
    assert resp.get_json()["period"]["preset"] == "7d"


def test_multibyte_utf8_payload_measured_by_encoded_bytes_not_character_count(client, monkeypatch):
    """
    1 karakter multi-byte (mis. emoji "🩺", 4 byte UTF-8) TIDAK BOLEH
    dihitung sebagai 1 "karakter" doang buat batas ukuran -- batasnya
    byte UTF-8 SUNGGUHAN. Body dengan BANYAK karakter tapi masih
    <=20000 byte encoded harus tetap DITERIMA; body yang python
    `len(str)`-nya kelihatan kecil tapi ENCODED byte-nya > 20000 harus
    DITOLAK.
    """
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    # Emoji 4-byte "🩺" -- tiap karakter Python = 4 byte UTF-8 KALAU
    # di-encode APA ADANYA (`ensure_ascii=False`, persis kayak
    # `JSON.stringify()` di browser beneran ngirim byte UTF-8 mentah,
    # BUKAN escape `\uXXXX` -- `json.dumps` bawaan Python defaultnya
    # `ensure_ascii=True` yang malah bikin tiap emoji jadi 12 byte ASCII
    # ter-escape, nggak merepresentasikan body multi-byte UTF-8 asli
    # yang mau diuji di sini).
    base = {"period": {"preset": "7d"}}
    base_len = len(json.dumps(base, ensure_ascii=False).encode("utf-8"))
    emoji_count = (MAX_CONSULTATION_BODY_BYTES - base_len - 20) // 4  # sisa margin buat kutip JSON dkk
    base["padding"] = "🩺" * emoji_count
    body_within = json.dumps(base, ensure_ascii=False).encode("utf-8")
    assert len(body_within) <= MAX_CONSULTATION_BODY_BYTES
    resp_within = client.post(
        f"/api/children/{child['id']}/doctor-consultation/preview",
        data=body_within, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp_within.status_code == 200

    # Sekarang lewatin batas byte-nya (bukan cuma nambah dikit karakter).
    base["padding"] = "🩺" * (emoji_count + 2000)
    body_over = json.dumps(base, ensure_ascii=False).encode("utf-8")
    assert len(body_over) > MAX_CONSULTATION_BODY_BYTES
    resp_over = client.post(
        f"/api/children/{child['id']}/doctor-consultation/preview",
        data=body_over, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp_over.status_code == 413


def test_malformed_json_below_size_limit_returns_400_not_413(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/preview",
        data=b'{"period": {"preset": "7d"} NOT VALID JSON',
        content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 400


@pytest.mark.parametrize("raw_body", [b"[1, 2, 3]", b'"just a string"', b"null", b"42"])
def test_non_object_json_below_size_limit_returns_400(client, monkeypatch, raw_body):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/preview",
        data=raw_body, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 400


def test_viewer_oversized_pdf_request_gets_403_not_413(client, monkeypatch):
    """
    Keputusan otorisasi-DULUAN yang didokumentasikan (lihat
    backend/docs/DOCTOR_CONSULTATION.md & komentar di
    export_consultation_pdf): Viewer ditolak `403` KONSISTEN terlepas
    ukuran body-nya -- TIDAK PERNAH kebedain (413 vs 403) dari luar
    berdasarkan seberapa besar body yang dia kirim, dan body-nya SENDIRI
    nggak pernah kesentuh (nol byte stream dibaca) buat request yang
    memang bakal ditolak apa pun isinya.
    """
    _freeze(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-oversized-pdf@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-oversized-pdf@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")

    big_body = _json_body_of_exact_size(MAX_CONSULTATION_BODY_BYTES + 5_000)
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/pdf",
        data=big_body, content_type="application/json", headers=auth_headers(viewer["token"]),
    )
    assert resp.status_code == 403
    # Filter ke entity_type konsultasi secara spesifik (BUKAN semua
    # audit event anak ini) -- `invite_and_join` di atas SENDIRI
    # sudah menghasilkan event `caregiver_membership` yang sah, nggak
    # ada hubungannya sama request PDF ini.
    assert CaregiverAuditEvent.query.filter_by(
        child_id=child["id"], entity_type="doctor_consultation_pdf_export",
    ).count() == 0


def test_owner_valid_sized_pdf_request_still_returns_a_pdf(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _pdf(client, user["token"], child["id"])
    assert resp.status_code == 200
    assert resp.content_type == "application/pdf"
    assert resp.data.startswith(b"%PDF-")


def test_oversized_pdf_request_from_authorized_role_creates_no_audit_event(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    big_body = _json_body_of_exact_size(MAX_CONSULTATION_BODY_BYTES + 5_000)
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/pdf",
        data=big_body, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 413
    assert CaregiverAuditEvent.query.filter_by(
        child_id=child["id"], entity_type="doctor_consultation_pdf_export",
    ).count() == 0


def test_global_max_content_length_config_is_unchanged(client):
    assert client.application.config["MAX_CONTENT_LENGTH"] == 6 * 1024 * 1024


# --------------------------------------------------------------------------
# 12. Konsistensi snapshot preview -> PDF (token bertanda tangan) -- bug
# review Agustus 2026, lihat backend/docs/DOCTOR_CONSULTATION.md bagian
# "Konsistensi snapshot preview -> PDF (token bertanda tangan)" +
# utils/consultation_snapshot.py.
# --------------------------------------------------------------------------


def test_preview_returns_a_consultation_snapshot_token(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    body = _preview(client, user["token"], child["id"]).get_json()
    assert isinstance(body.get("snapshot_token"), str)
    assert len(body["snapshot_token"]) > 20


def test_snapshot_token_claims_contain_only_approved_fields(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    token = _preview(client, user["token"], child["id"]).get_json()["snapshot_token"]
    with client.application.app_context():
        claims = decode_consultation_snapshot_token(token, child_id=child["id"], user_id=user["id"])
    assert set(claims.keys()) == {"v", "child_id", "user_id", "preview_at", "digest"}


def test_no_sensitive_data_in_decoded_claims_or_serialized_token(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    secret_q = "RAHASIA-pertanyaan-unik-xyz"
    secret_note = "RAHASIA-catatan-unik-abc"
    preview_body = _preview(
        client, user["token"], child["id"], sections=["questions", "note"], questions=secret_q, note=secret_note,
    ).get_json()
    token = preview_body["snapshot_token"]

    with client.application.app_context():
        claims = decode_consultation_snapshot_token(token, child_id=child["id"], user_id=user["id"])
    haystack = token + json.dumps(claims)
    for secret in (secret_q, secret_note, "RAHASIA", "pertanyaan", "catatan"):
        assert secret not in haystack


def test_valid_unchanged_snapshot_produces_a_pdf(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _pdf(client, user["token"], child["id"])
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")


def test_pdf_renderer_receives_a_report_logically_identical_to_preview(client, monkeypatch):
    """Requirement: 'the renderer receives a report logically identical to the previewed report.' Diverifikasi langsung dengan menangkap argumen render_consultation_pdf yang SUNGGUHAN dipanggil endpoint, bukan cuma percaya status 200."""
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(MedicationLog(child_id=child["id"], medication_name="Amoxicillin Unik", timestamp=FAKE_NOW))
    db.session.commit()

    preview_body = _preview(client, user["token"], child["id"], sections=["medication"]).get_json()
    token = preview_body["snapshot_token"]

    original_render = consultation_routes_module.render_consultation_pdf
    captured = {}

    def _capture(report):
        captured["report"] = report
        return original_render(report)

    monkeypatch.setattr(consultation_routes_module, "render_consultation_pdf", _capture)

    resp = _pdf(client, user["token"], child["id"], sections=["medication"], snapshot_token=token)
    assert resp.status_code == 200
    assert captured["report"]["sections"] == preview_body["sections"]
    assert captured["report"]["period"] == preview_body["period"]
    assert captured["report"]["sections"]["medication"]["entries"][0]["medication_name"] == "Amoxicillin Unik"


def test_later_wall_clock_alone_does_not_invalidate_unchanged_snapshot(client, monkeypatch):
    """Requirement #6: endpoint PDF TIDAK PERNAH memakai now_wib() BARU buat MEMBANGUN ULANG laporan (cuma buat metadata audit/nama file) -- wall-clock maju TIDAK memengaruhi kecocokan digest selama data DB-nya sendiri tidak berubah."""
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    token = _preview(client, user["token"], child["id"]).get_json()["snapshot_token"]

    later = FAKE_NOW + timedelta(hours=2)
    monkeypatch.setattr(consultation_routes_module, "now_wib", lambda: later)

    resp = _pdf(client, user["token"], child["id"], snapshot_token=token)
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")


def test_adding_a_selected_section_record_after_preview_causes_409(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    token = _preview(client, user["token"], child["id"], sections=["medication"]).get_json()["snapshot_token"]

    db.session.add(MedicationLog(child_id=child["id"], medication_name="Obat Baru", timestamp=FAKE_NOW))
    db.session.commit()

    resp = _pdf(client, user["token"], child["id"], sections=["medication"], snapshot_token=token)
    assert resp.status_code == 409
    assert "Buat pratinjau ulang" in resp.get_json()["error"]


def test_editing_a_selected_section_record_after_preview_causes_409(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    log = MedicationLog(child_id=child["id"], medication_name="Obat Lama", timestamp=FAKE_NOW)
    db.session.add(log)
    db.session.commit()

    token = _preview(client, user["token"], child["id"], sections=["medication"]).get_json()["snapshot_token"]

    log.medication_name = "Obat Diubah"
    db.session.commit()

    resp = _pdf(client, user["token"], child["id"], sections=["medication"], snapshot_token=token)
    assert resp.status_code == 409


def test_deleting_a_selected_section_record_after_preview_causes_409(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    log = MedicationLog(child_id=child["id"], medication_name="Obat Untuk Dihapus", timestamp=FAKE_NOW)
    db.session.add(log)
    db.session.commit()

    token = _preview(client, user["token"], child["id"], sections=["medication"]).get_json()["snapshot_token"]

    db.session.delete(log)
    db.session.commit()

    resp = _pdf(client, user["token"], child["id"], sections=["medication"], snapshot_token=token)
    assert resp.status_code == 409


def test_changes_in_an_unselected_section_do_not_invalidate_snapshot(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    token = _preview(client, user["token"], child["id"], sections=["feeding"]).get_json()["snapshot_token"]

    # `medication` TIDAK dipilih -- perubahan di section ini TIDAK BOLEH memengaruhi digest.
    db.session.add(MedicationLog(child_id=child["id"], medication_name="Obat Tak Terpilih", timestamp=FAKE_NOW))
    db.session.commit()

    resp = _pdf(client, user["token"], child["id"], sections=["feeding"], snapshot_token=token)
    assert resp.status_code == 200


def test_medical_profile_change_causes_409_when_section_selected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    token = _preview(client, user["token"], child["id"], sections=["medical_profile"]).get_json()["snapshot_token"]

    client.put(
        f"/api/children/{child['id']}/medical-profile",
        json={"blood_type": "O+"}, headers=auth_headers(user["token"]),
    )

    resp = _pdf(client, user["token"], child["id"], sections=["medical_profile"], snapshot_token=token)
    assert resp.status_code == 409


def test_medical_profile_change_does_not_invalidate_preview_excluding_that_section(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    token = _preview(client, user["token"], child["id"], sections=["feeding"]).get_json()["snapshot_token"]

    client.put(
        f"/api/children/{child['id']}/medical-profile",
        json={"blood_type": "O+"}, headers=auth_headers(user["token"]),
    )

    resp = _pdf(client, user["token"], child["id"], sections=["feeding"], snapshot_token=token)
    assert resp.status_code == 200


def test_child_display_data_change_after_preview_causes_409(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"], name="Nama Lama")
    token = _preview(client, user["token"], child["id"], sections=["child_summary"]).get_json()["snapshot_token"]

    client.put(
        f"/api/children/{child['id']}", json={"nickname": "Panggilan Baru"}, headers=auth_headers(user["token"]),
    )

    resp = _pdf(client, user["token"], child["id"], sections=["child_summary"], snapshot_token=token)
    assert resp.status_code == 409


def test_changed_questions_cannot_be_exported_with_old_token(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    token = _preview(
        client, user["token"], child["id"], sections=["questions"], questions="Pertanyaan asli",
    ).get_json()["snapshot_token"]

    resp = _pdf(
        client, user["token"], child["id"], sections=["questions"], questions="Pertanyaan DIUBAH", snapshot_token=token,
    )
    assert resp.status_code == 409


def test_changed_note_cannot_be_exported_with_old_token(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    token = _preview(
        client, user["token"], child["id"], sections=["note"], note="Catatan asli",
    ).get_json()["snapshot_token"]

    resp = _pdf(
        client, user["token"], child["id"], sections=["note"], note="Catatan DIUBAH", snapshot_token=token,
    )
    assert resp.status_code == 409


def test_changed_section_selection_cannot_be_exported_with_old_token(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    token = _preview(client, user["token"], child["id"], sections=["feeding"]).get_json()["snapshot_token"]

    resp = _pdf(client, user["token"], child["id"], sections=["feeding", "sleep"], snapshot_token=token)
    assert resp.status_code == 409


def test_changed_period_cannot_be_exported_with_old_token(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    token = _preview(client, user["token"], child["id"], period={"preset": "7d"}).get_json()["snapshot_token"]

    resp = _pdf(client, user["token"], child["id"], period={"preset": "14d"}, snapshot_token=token)
    assert resp.status_code == 409


def test_canonicalization_is_stable_regardless_of_dict_key_order():
    report_a = {
        "child_id": 1, "child_display_name": "Dedek",
        "period": {
            "preset": "7d", "start_date": "2026-08-17", "end_date": "2026-08-23",
            "timezone": "Asia/Jakarta", "days": 7,
        },
        "generated_at": "2026-08-23T10:00:00+07:00", "disclaimer": "d", "privacy_note": "p",
        "generated_statement": "g", "included_sections": ["feeding"], "sensitive_sections_included": [],
        "sections": {"feeding": {"total_events": 3, "by_type": {"asi_langsung": 3, "sufor": 0}}},
    }
    report_b = dict(reversed(list(report_a.items())))
    report_b["period"] = dict(reversed(list(report_a["period"].items())))
    report_b["sections"] = {"feeding": dict(reversed(list(report_a["sections"]["feeding"].items())))}
    report_b["sections"]["feeding"]["by_type"] = dict(reversed(list(report_a["sections"]["feeding"]["by_type"].items())))

    assert digest_consultation_report(report_a) == digest_consultation_report(report_b)


def test_deterministic_ordering_prevents_false_mismatch_for_same_date_records(client, monkeypatch):
    """
    Regresi buat perbaikan tie-breaker `id` di utils/consultation_report.py
    (requirement: 'deterministic database ordering prevents false
    mismatches') -- 2 record ILLNESS dengan `start_date` PERSIS SAMA
    TIDAK BOLEH bikin preview & rebuild PDF menghasilkan digest yang
    beda gara-gara urutan baris SQLite yang (tanpa tie-breaker) tidak
    dijamin stabil.
    """
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    db.session.add(IllnessLog(child_id=child["id"], illness_name="Flu", start_date=FAKE_TODAY))
    db.session.add(IllnessLog(child_id=child["id"], illness_name="Batuk", start_date=FAKE_TODAY))
    db.session.commit()

    token = _preview(client, user["token"], child["id"], sections=["illness"]).get_json()["snapshot_token"]
    resp = _pdf(client, user["token"], child["id"], sections=["illness"], snapshot_token=token)
    assert resp.status_code == 200


def test_expired_consultation_snapshot_token_is_rejected(client, monkeypatch):
    """
    Token digenerate LANGSUNG lewat `generate_consultation_snapshot_token`
    (bukan lewat HTTP POST .../preview) dengan `time.time()` dibekukan
    ke 1 jam yang lalu HANYA selama panggilan itu -- BUKAN lewat
    endpoint preview beneran, yang bakal ikut merusak token LOGIN
    (`user["token"]`, juga bertanda tangan itsdangerous berbasis
    `time.time()`) kalau jam sistem ikut dimundurkan saat request HTTP
    itu diproses.
    """
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    from utils.consultation_snapshot import generate_consultation_snapshot_token
    real_time = time.time
    with client.application.app_context():
        with patch("time.time", return_value=real_time() - 3600):
            token = generate_consultation_snapshot_token(
                child_id=child["id"], user_id=user["id"],
                preview_at=FAKE_NOW.isoformat(), report_digest="expired-token-digest-never-checked",
            )

    resp = _pdf(client, user["token"], child["id"], snapshot_token=token)
    assert resp.status_code == 400


def test_tampered_consultation_snapshot_token_is_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    token = _preview(client, user["token"], child["id"]).get_json()["snapshot_token"]

    tampered = _tamper_token(token)
    resp = _pdf(client, user["token"], child["id"], snapshot_token=tampered)
    assert resp.status_code == 400


def test_wrong_child_consultation_snapshot_token_is_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child_a = create_child(client, user["token"], name="Anak A")
    child_b = create_child(client, user["token"], name="Anak B")
    token_for_a = _preview(client, user["token"], child_a["id"]).get_json()["snapshot_token"]

    resp = _pdf(client, user["token"], child_b["id"], snapshot_token=token_for_a)
    assert resp.status_code == 403


def test_wrong_user_consultation_snapshot_token_is_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-consnap1@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-consnap1@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")

    token_for_owner = _preview(client, owner["token"], child["id"]).get_json()["snapshot_token"]
    resp = _pdf(client, editor["token"], child["id"], snapshot_token=token_for_owner)
    assert resp.status_code == 403


def test_missing_consultation_snapshot_token_is_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = _pdf(client, user["token"], child["id"], snapshot_token=None)
    assert resp.status_code == 400


def test_invalid_schema_version_token_is_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    with client.application.app_context():
        from utils.consultation_snapshot import CONSULTATION_SNAPSHOT_SALT
        from utils.snapshot_token import generate_signed_snapshot_token
        bad_token = generate_signed_snapshot_token(
            salt=CONSULTATION_SNAPSHOT_SALT,
            claims={
                "v": 999, "child_id": child["id"], "user_id": user["id"],
                "preview_at": FAKE_NOW.isoformat(), "digest": "whatever",
            },
        )
    resp = _pdf(client, user["token"], child["id"], snapshot_token=bad_token)
    assert resp.status_code == 400


def test_pdf_rejects_declared_oversized_body(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    big_body = _json_body_of_exact_size(MAX_CONSULTATION_BODY_BYTES + 5_000)
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/pdf",
        data=big_body, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 413


def test_pdf_rejects_missing_content_length_oversized_body(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    big_body = _json_body_of_exact_size(MAX_CONSULTATION_BODY_BYTES + 5_000)
    status_code, _ = _post_without_content_length(
        client, f"/api/children/{child['id']}/doctor-consultation/pdf", user["token"], big_body,
    )
    assert status_code == 413


def test_pdf_body_at_exact_boundary_passes_size_check(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    body = _json_body_of_exact_size(MAX_CONSULTATION_BODY_BYTES, extra={"snapshot_token": "x"})
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/pdf",
        data=body, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp.status_code != 413


def test_pdf_body_one_byte_over_boundary_is_rejected(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    body = _json_body_of_exact_size(MAX_CONSULTATION_BODY_BYTES + 1, extra={"snapshot_token": "x"})
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/pdf",
        data=body, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 413


def test_pdf_rejects_multibyte_utf8_oversized_body(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    base = {"period": {"preset": "7d"}}
    base_len = len(json.dumps(base, ensure_ascii=False).encode("utf-8"))
    emoji_count = (MAX_CONSULTATION_BODY_BYTES - base_len + 5_000) // 4
    base["padding"] = "🩺" * emoji_count
    body_over = json.dumps(base, ensure_ascii=False).encode("utf-8")
    assert len(body_over) > MAX_CONSULTATION_BODY_BYTES
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/pdf",
        data=body_over, content_type="application/json", headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 413


def test_pdf_rejects_malformed_json_body(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/pdf",
        data="{not valid json", headers={**auth_headers(user["token"]), "Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_pdf_rejects_non_object_json_body(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    resp = client.post(
        f"/api/children/{child['id']}/doctor-consultation/pdf", json=["bukan", "objek"], headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 400


def test_viewer_gets_same_403_for_pdf_regardless_of_token_validity(client, monkeypatch):
    _freeze(monkeypatch)
    owner = register(client, name="Pemilik", email="owner-consnap2@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-consnap2@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")

    valid_owner_token = _preview(client, owner["token"], child["id"]).get_json()["snapshot_token"]

    resp_missing = _pdf(client, viewer["token"], child["id"], snapshot_token=None)
    resp_garbage = _pdf(client, viewer["token"], child["id"], snapshot_token="garbage")
    resp_not_theirs = _pdf(client, viewer["token"], child["id"], snapshot_token=valid_owner_token)

    bodies = [r.get_json() for r in (resp_missing, resp_garbage, resp_not_theirs)]
    for resp in (resp_missing, resp_garbage, resp_not_theirs):
        assert resp.status_code == 403
    assert all(b == bodies[0] for b in bodies)


def test_no_pdf_renderer_called_for_rejected_or_stale_requests(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("render_consultation_pdf should not be called for a rejected/stale request")

    monkeypatch.setattr(consultation_routes_module, "render_consultation_pdf", _fail_if_called)

    assert _pdf(client, user["token"], child["id"], snapshot_token=None).status_code == 400

    token = _preview(client, user["token"], child["id"]).get_json()["snapshot_token"]
    assert _pdf(client, user["token"], child["id"], snapshot_token=_tamper_token(token)).status_code == 400

    token2 = _preview(client, user["token"], child["id"], sections=["medication"]).get_json()["snapshot_token"]
    db.session.add(MedicationLog(child_id=child["id"], medication_name="Baru", timestamp=FAKE_NOW))
    db.session.commit()
    assert _pdf(
        client, user["token"], child["id"], sections=["medication"], snapshot_token=token2,
    ).status_code == 409


def test_no_audit_event_for_rejected_or_stale_pdf_requests(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    before = CaregiverAuditEvent.query.filter_by(
        child_id=child["id"], entity_type="doctor_consultation_pdf_export",
    ).count()

    _pdf(client, user["token"], child["id"], snapshot_token=None)
    _pdf(client, user["token"], child["id"], snapshot_token="garbage-token")
    token = _preview(client, user["token"], child["id"], sections=["medication"]).get_json()["snapshot_token"]
    db.session.add(MedicationLog(child_id=child["id"], medication_name="Baru2", timestamp=FAKE_NOW))
    db.session.commit()
    _pdf(client, user["token"], child["id"], sections=["medication"], snapshot_token=token)

    after = CaregiverAuditEvent.query.filter_by(
        child_id=child["id"], entity_type="doctor_consultation_pdf_export",
    ).count()
    assert after == before


def test_successful_pdf_export_creates_exactly_one_audit_event(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    before = CaregiverAuditEvent.query.filter_by(
        child_id=child["id"], entity_type="doctor_consultation_pdf_export",
    ).count()

    resp = _pdf(client, user["token"], child["id"])
    assert resp.status_code == 200

    after = CaregiverAuditEvent.query.filter_by(
        child_id=child["id"], entity_type="doctor_consultation_pdf_export",
    ).count()
    assert after == before + 1


def test_emergency_card_token_cannot_be_used_for_doctor_consultation(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])

    from utils.emergency_card_snapshot import generate_snapshot_token as generate_emergency_card_token
    with client.application.app_context():
        foreign_token = generate_emergency_card_token(
            child_id=child["id"], user_id=user["id"], preview_at=FAKE_NOW.isoformat(), report_digest="whatever",
        )

    resp = _pdf(client, user["token"], child["id"], snapshot_token=foreign_token)
    assert resp.status_code == 400


def test_doctor_consultation_token_cannot_be_used_for_emergency_card(client, monkeypatch):
    _freeze(monkeypatch)
    user = register(client)
    child = create_child(client, user["token"])
    consultation_token = _preview(client, user["token"], child["id"]).get_json()["snapshot_token"]

    resp = client.post(
        f"/api/children/{child['id']}/emergency-card/pdf",
        json={"snapshot_token": consultation_token}, headers=auth_headers(user["token"]),
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# 13. Midnight race di endpoint preview (bug review Agustus 2026) --
# `preview_consultation()` SEBELUMNYA memanggil `today_wib()` DULUAN
# (buat validasi period) baru `now_wib()` BELAKANGAN (buat isi laporan +
# token) -- 2 pemanggilan jam sistem TERPISAH, kalau eksekusi kebetulan
# melewati tengah malam WIB PERSIS di antara keduanya, `period` bisa
# ke-resolve pakai tanggal LAMA sementara `generated_at`/`preview_at`
# token pakai tanggal BARU, bikin PDF yang laporannya BENERAN belum
# berubah ditolak `409` palsu. Perbaikan: `now_wib()` di-sample TEPAT
# SEKALI, `now.date()` dipakai buat resolusi period, endpoint preview
# TIDAK PERNAH lagi memanggil `today_wib()` sama sekali.
# --------------------------------------------------------------------------


def _today_wib_should_not_be_called():
    raise AssertionError("preview_consultation should never call today_wib()")


def test_preview_calls_now_wib_exactly_once_and_never_calls_today_wib(client, monkeypatch):
    call_count = {"now_wib": 0}

    def _counting_now_wib():
        call_count["now_wib"] += 1
        return FAKE_NOW

    monkeypatch.setattr(consultation_routes_module, "now_wib", _counting_now_wib)
    monkeypatch.setattr(consultation_routes_module, "today_wib", _today_wib_should_not_be_called)

    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"])

    assert resp.status_code == 200
    assert call_count["now_wib"] == 1


def test_period_end_date_equals_sampled_now_date(client, monkeypatch):
    monkeypatch.setattr(consultation_routes_module, "now_wib", lambda: FAKE_NOW)
    monkeypatch.setattr(consultation_routes_module, "today_wib", _today_wib_should_not_be_called)

    user = register(client)
    child = create_child(client, user["token"])
    resp = _preview(client, user["token"], child["id"])

    assert resp.status_code == 200
    assert resp.get_json()["period"]["end_date"] == FAKE_NOW.date().isoformat()


def test_token_preview_at_and_report_generated_at_match_sampled_now(client, monkeypatch):
    monkeypatch.setattr(consultation_routes_module, "now_wib", lambda: FAKE_NOW)
    monkeypatch.setattr(consultation_routes_module, "today_wib", _today_wib_should_not_be_called)

    user = register(client)
    child = create_child(client, user["token"])
    body = _preview(client, user["token"], child["id"]).get_json()

    assert body["generated_at"] == FAKE_NOW.isoformat() + "+07:00"
    with client.application.app_context():
        claims = decode_consultation_snapshot_token(
            body["snapshot_token"], child_id=child["id"], user_id=user["id"],
        )
    assert claims["preview_at"] == FAKE_NOW.isoformat()


def test_period_presets_use_sampled_date_consistently_across_7_14_30_days(client, monkeypatch):
    monkeypatch.setattr(consultation_routes_module, "now_wib", lambda: FAKE_NOW)
    monkeypatch.setattr(consultation_routes_module, "today_wib", _today_wib_should_not_be_called)

    user = register(client)
    child = create_child(client, user["token"])
    for preset, days in (("7d", 7), ("14d", 14), ("30d", 30)):
        resp = _preview(client, user["token"], child["id"], period={"preset": preset})
        assert resp.status_code == 200, resp.get_json()
        period = resp.get_json()["period"]
        assert period["end_date"] == FAKE_NOW.date().isoformat()
        assert period["start_date"] == (FAKE_NOW.date() - timedelta(days=days - 1)).isoformat()


def test_midnight_race_no_longer_causes_false_409(client, monkeypatch):
    """
    Simulasi EKSPLISIT bug lama: `now_wib()` dibekukan ke waktu TEPAT
    setelah tengah malam WIB (00:00:01), dan `today_wib()` dibuat
    MELEMPAR AssertionError kalau kepanggil sama sekali SELAMA request
    preview -- kalau endpoint preview MASIH memanggil `today_wib()` di
    jalur mana pun (bug lama), test ini langsung gagal KERAS, bukan
    cuma "kebetulan lolos" gara-gara waktu tes yang tidak melewati
    tengah malam beneran (TIDAK ADA wall-clock sleep di sini SAMA
    SEKALI -- deterministik).
    """
    just_after_midnight = datetime(2026, 8, 25, 0, 0, 1)
    user = register(client)
    child = create_child(client, user["token"])

    with monkeypatch.context() as m:
        m.setattr(consultation_routes_module, "now_wib", lambda: just_after_midnight)
        m.setattr(consultation_routes_module, "today_wib", _today_wib_should_not_be_called)
        preview_resp = _preview(client, user["token"], child["id"])

    assert preview_resp.status_code == 200
    preview_body = preview_resp.get_json()
    assert preview_body["period"]["end_date"] == "2026-08-25"

    # Endpoint PDF SENGAJA TETAP boleh memanggil today_wib() (perilaku
    # ekspor yang TIDAK diubah tugas ini, murni buat validasi bentuk
    # payload yang dikirim ulang) -- dibekukan normal di sini (bukan
    # dilarang) buat memverifikasi PDF-nya sendiri BERHASIL 200 tanpa
    # 409 palsu, dengan database TIDAK PERNAH tersentuh sama sekali
    # antara preview & PDF (tidak ada tulis apa pun di test ini).
    monkeypatch.setattr(consultation_routes_module, "now_wib", lambda: just_after_midnight)
    monkeypatch.setattr(consultation_routes_module, "today_wib", lambda: just_after_midnight.date())
    resp = _pdf(client, user["token"], child["id"], snapshot_token=preview_body["snapshot_token"])
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")


def test_genuine_database_change_after_preview_still_causes_409_after_midnight_fix(client, monkeypatch):
    """Requirement #8: perbaikan midnight race TIDAK BOLEH melemahkan deteksi perubahan data ASLI -- 409 tetap terjadi buat data yang beneran berubah."""
    just_after_midnight = datetime(2026, 8, 25, 0, 0, 1)
    monkeypatch.setattr(consultation_routes_module, "now_wib", lambda: just_after_midnight)
    monkeypatch.setattr(consultation_routes_module, "today_wib", lambda: just_after_midnight.date())
    user = register(client)
    child = create_child(client, user["token"])

    token = _preview(client, user["token"], child["id"], sections=["medication"]).get_json()["snapshot_token"]

    db.session.add(MedicationLog(
        child_id=child["id"], medication_name="Obat Baru Setelah Preview", timestamp=just_after_midnight,
    ))
    db.session.commit()

    resp = _pdf(client, user["token"], child["id"], sections=["medication"], snapshot_token=token)
    assert resp.status_code == 409


def test_successful_export_after_midnight_fix_creates_exactly_one_sanitized_audit_event(client, monkeypatch):
    just_after_midnight = datetime(2026, 8, 25, 0, 0, 1)
    monkeypatch.setattr(consultation_routes_module, "now_wib", lambda: just_after_midnight)
    monkeypatch.setattr(consultation_routes_module, "today_wib", lambda: just_after_midnight.date())
    user = register(client)
    child = create_child(client, user["token"])
    before = CaregiverAuditEvent.query.filter_by(
        child_id=child["id"], entity_type="doctor_consultation_pdf_export",
    ).count()

    resp = _pdf(client, user["token"], child["id"])
    assert resp.status_code == 200

    events = CaregiverAuditEvent.query.filter_by(
        child_id=child["id"], entity_type="doctor_consultation_pdf_export",
    ).all()
    assert len(events) == before + 1
    event = events[-1]
    assert event.changed_fields_json is None
    assert event.entity_id == 0
