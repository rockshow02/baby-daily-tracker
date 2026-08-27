from datetime import date

from extensions import db
from models import DoctorVisitLog, GrowthMeasurement, IllnessLog, MilestoneLog, TemperatureLog
from tests.conftest import auth_headers, create_child, register
from utils.timezone_utils import now_wib


def test_timeline_combines_sorts_filters_and_minimizes_health_text(client, app):
    owner = register(client)
    child = create_child(client, owner["token"])
    headers = auth_headers(owner["token"])
    with app.app_context():
        db.session.add_all([
            MilestoneLog(child_id=child["id"], created_by_user_id=owner["id"],
                milestone_type="custom", custom_label="Tepuk tangan", achieved_date=date(2026, 8, 20)),
            GrowthMeasurement(child_id=child["id"], created_by_user_id=owner["id"],
                measured_date=date(2026, 8, 21), weight_kg=7.2, height_cm=65),
            IllnessLog(child_id=child["id"], created_by_user_id=owner["id"],
                illness_name="RAHASIA-PENYAKIT", symptoms="RAHASIA-GEJALA", start_date=date(2026, 8, 22)),
            DoctorVisitLog(child_id=child["id"], created_by_user_id=owner["id"],
                visit_date=date(2026, 8, 23), diagnosis="RAHASIA-DIAGNOSIS"),
            TemperatureLog(child_id=child["id"], created_by_user_id=owner["id"],
                timestamp=now_wib(), temperature_celsius=37.5, method="ketiak"),
        ])
        db.session.commit()
    response = client.get(f"/api/children/{child['id']}/development-timeline", headers=headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["items"] == sorted(payload["items"], key=lambda x: (x["date"], x["id"]), reverse=True)
    rendered = str(payload)
    assert "RAHASIA-PENYAKIT" not in rendered
    assert "RAHASIA-GEJALA" not in rendered
    assert "RAHASIA-DIAGNOSIS" not in rendered
    growth = client.get(f"/api/children/{child['id']}/development-timeline?categories=growth", headers=headers)
    assert growth.status_code == 200
    assert [item["type"] for item in growth.get_json()["items"]] == ["growth"]


def test_timeline_requires_access_and_validates_parameters(client):
    owner = register(client)
    child = create_child(client, owner["token"])
    headers = auth_headers(owner["token"])
    assert client.get(f"/api/children/{child['id']}/development-timeline",
        headers={"Authorization": "Bearer invalid"}).status_code == 404
    assert client.get(f"/api/children/{child['id']}/development-timeline?categories=secret",
        headers=headers).status_code == 400
    assert client.get(f"/api/children/{child['id']}/development-timeline?from=2026-09-01&to=2026-08-01",
        headers=headers).status_code == 400
