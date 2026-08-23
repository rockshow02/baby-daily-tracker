"""
Regresi buat fitur PDF export UMUM yang sudah ada
(`GET /children/<id>/export-pdf`, routes/report_routes.py) --
SEBELUM Doctor Consultation Workflow ditambahkan, fitur ini TIDAK
PUNYA test sama sekali. File ini CUMA mengunci perilaku yang SUDAH ADA
(tidak ada perubahan kode di report_routes.py), supaya perubahan lain
di masa depan nggak diam-diam meregresi export laporan umum ini.
"""
from datetime import timedelta

from tests.conftest import auth_headers, create_child, register
from tests.test_roles_permissions import invite_and_join


def _export(client, token, child_id):
    return client.get(f"/api/children/{child_id}/export-pdf", headers=auth_headers(token))


def test_owner_can_export_general_pdf(client):
    user = register(client)
    child = create_child(client, user["token"])
    resp = _export(client, user["token"], child["id"])
    assert resp.status_code == 200
    assert resp.content_type == "application/pdf"
    assert resp.data.startswith(b"%PDF-")
    assert "attachment" in resp.headers.get("Content-Disposition", "")


def test_editor_can_export_general_pdf(client):
    owner = register(client, name="Pemilik", email="owner-genpdf@example.com")
    child = create_child(client, owner["token"])
    editor = register(client, name="Editor", email="editor-genpdf@example.com")
    invite_and_join(client, owner["token"], child["id"], editor["token"], "editor")
    resp = _export(client, editor["token"], child["id"])
    assert resp.status_code == 200


def test_viewer_can_export_general_pdf(client):
    """Beda dari PDF konsultasi (viewer ditolak) -- laporan umum yang SUDAH ADA ini SENGAJA nggak dibatasi role, lihat report_routes.py:_owned_child (cuma butuh akses baca)."""
    owner = register(client, name="Pemilik", email="owner-genpdf2@example.com")
    child = create_child(client, owner["token"])
    viewer = register(client, name="Viewer", email="viewer-genpdf@example.com")
    invite_and_join(client, owner["token"], child["id"], viewer["token"], "viewer")
    resp = _export(client, viewer["token"], child["id"])
    assert resp.status_code == 200


def test_unauthenticated_export_is_rejected(client):
    # SENGAJA nggak pernah register()/login di client ini -- lihat catatan
    # yang sama di tests/test_doctor_consultation.py soal cookie session
    # test client Flask yang persisten antar request dalam 1 test.
    resp = client.get("/api/children/1/export-pdf")
    assert resp.status_code == 404


def test_inaccessible_child_returns_404(client):
    owner = register(client, name="Pemilik", email="owner-genpdf3@example.com")
    child = create_child(client, owner["token"])
    outsider = register(client, name="Orang Lain", email="outsider-genpdf@example.com")
    resp = _export(client, outsider["token"], child["id"])
    assert resp.status_code == 404


def test_export_works_with_no_data_at_all(client):
    user = register(client)
    child = create_child(client, user["token"])
    resp = _export(client, user["token"], child["id"])
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")
