from datetime import date

from extensions import db
from models import CaregiverAuditEvent, GrowthMeasurement, MilestoneLog
from tests.conftest import auth_headers, create_child, register


def _seed(app, child_id, user_id):
    with app.app_context():
        db.session.add(MilestoneLog(child_id=child_id, created_by_user_id=user_id,
            milestone_type="custom", custom_label="Tepuk tangan", achieved_date=date(2026, 8, 12)))
        db.session.add(GrowthMeasurement(child_id=child_id, created_by_user_id=user_id,
            measured_date=date(2026, 8, 15), weight_kg=7.2, height_cm=65))
        db.session.commit()


def test_monthly_story_preview_and_snapshot_safe_pdf(client, app):
    owner = register(client); child = create_child(client, owner["token"])
    headers = auth_headers(owner["token"]); _seed(app, child["id"], owner["id"])
    payload = {"month": "2026-08", "parent_note": "Bulan yang menyenangkan", "selected_photo_ids": []}
    preview = client.post(f"/api/children/{child['id']}/monthly-story/preview", json=payload, headers=headers)
    assert preview.status_code == 200, preview.get_json()
    report = preview.get_json()
    assert report["counts"]["milestones"] == 1
    assert report["growth"][0]["weight_kg"] == 7.2
    assert report["capabilities"]["can_export"] is True
    token = report["snapshot_token"]
    exported = client.post(f"/api/children/{child['id']}/monthly-story/pdf",
        json={**payload, "snapshot_token": token}, headers=headers)
    assert exported.status_code == 200
    assert exported.content_type == "application/pdf"
    with app.app_context():
        events = CaregiverAuditEvent.query.filter_by(entity_type="monthly_story_pdf_export").all()
        assert len(events) == 1 and events[0].changed_fields_json is None


def test_monthly_story_rejects_stale_snapshot_without_audit(client, app):
    owner = register(client); child = create_child(client, owner["token"])
    headers = auth_headers(owner["token"]); _seed(app, child["id"], owner["id"])
    payload = {"month": "2026-08", "parent_note": "", "selected_photo_ids": []}
    preview = client.post(f"/api/children/{child['id']}/monthly-story/preview", json=payload, headers=headers).get_json()
    with app.app_context():
        db.session.add(MilestoneLog(child_id=child["id"], created_by_user_id=owner["id"],
            milestone_type="custom", custom_label="Momen baru", achieved_date=date(2026, 8, 20)))
        db.session.commit()
    response = client.post(f"/api/children/{child['id']}/monthly-story/pdf",
        json={**payload, "snapshot_token": preview["snapshot_token"]}, headers=headers)
    assert response.status_code == 409
    with app.app_context():
        assert CaregiverAuditEvent.query.filter_by(entity_type="monthly_story_pdf_export").count() == 0


def test_monthly_story_validates_month_note_and_token(client):
    owner = register(client); child = create_child(client, owner["token"]); headers = auth_headers(owner["token"])
    base = f"/api/children/{child['id']}/monthly-story"
    assert client.post(f"{base}/preview", json={"month": "2999-01"}, headers=headers).status_code == 400
    assert client.post(f"{base}/preview", json={"month": "2026-08", "parent_note": "x"*1001}, headers=headers).status_code == 400
    assert client.post(f"{base}/pdf", json={"month": "2026-08"}, headers=headers).status_code == 400
