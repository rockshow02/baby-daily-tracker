from datetime import date, timedelta

from extensions import db
from models import ChildVaccination, VaccineSchedule
from tests.conftest import auth_headers, register
from utils.vaccination_planner import vaccination_state, vaccination_summary


def test_state_boundaries_and_given_override():
    birth = date(2026, 1, 31)
    recommended = date(2026, 2, 28)
    assert vaccination_state(birth_date=birth, recommended_age_months=1, reference_date=recommended - timedelta(days=15), given=False)[0] == "upcoming"
    assert vaccination_state(birth_date=birth, recommended_age_months=1, reference_date=recommended - timedelta(days=14), given=False)[0] == "due"
    assert vaccination_state(birth_date=birth, recommended_age_months=1, reference_date=recommended + timedelta(days=30), given=False)[0] == "due"
    assert vaccination_state(birth_date=birth, recommended_age_months=1, reference_date=recommended + timedelta(days=31), given=False)[0] == "overdue"
    assert vaccination_state(birth_date=birth, recommended_age_months=1, reference_date=recommended + timedelta(days=500), given=True)[0] == "given"


def test_summary_counts_known_states():
    result = vaccination_summary([{"state": "given"}, {"state": "due"}, {"state": "overdue"}, {"state": "upcoming"}])
    assert result == {"total": 4, "given": 1, "upcoming": 1, "due": 1, "overdue": 1}


def _setup(client):
    user = register(client)
    response = client.post(
        "/api/children",
        json={"name": "Bayi", "birth_date": "2026-01-01", "gender": "L"},
        headers=auth_headers(user["token"]),
    )
    assert response.status_code == 201
    child = response.get_json()
    vaccine = VaccineSchedule(vaccine_name="BCG", recommended_age_months=1, category="wajib", order_index=1)
    db.session.add(vaccine)
    db.session.commit()
    return user, child, vaccine


def test_list_returns_planner_state_summary_capability_and_disclaimer(client, monkeypatch):
    user, child, vaccine = _setup(client)
    monkeypatch.setattr("routes.children_routes.today_wib", lambda: date(2026, 3, 31))
    response = client.get(f"/api/children/{child['id']}/vaccinations", headers=auth_headers(user["token"]))
    assert response.status_code == 200
    body = response.get_json()
    item = body["vaccinations"][0]
    assert item["recommended_date"] == "2026-02-01"
    assert item["state"] == "overdue"
    assert body["summary"]["overdue"] == 1
    assert body["can_update"] is True
    assert "dokter" in body["disclaimer"].lower()


def test_update_rejects_invalid_payload_atomically(client, monkeypatch):
    user, child, vaccine = _setup(client)
    monkeypatch.setattr("routes.children_routes.today_wib", lambda: date(2026, 3, 31))
    response = client.post(
        f"/api/children/{child['id']}/vaccinations",
        json={"items": [
            {"vaccine_schedule_id": vaccine.id, "given": True, "given_date": "2026-03-01"},
            {"vaccine_schedule_id": 999999, "given": True},
        ]},
        headers=auth_headers(user["token"]),
    )
    assert response.status_code == 400
    assert ChildVaccination.query.filter_by(child_id=child["id"]).count() == 0


def test_update_rejects_non_boolean_future_and_prebirth_values(client, monkeypatch):
    user, child, vaccine = _setup(client)
    monkeypatch.setattr("routes.children_routes.today_wib", lambda: date(2026, 3, 31))
    url = f"/api/children/{child['id']}/vaccinations"
    for item in [
        {"vaccine_schedule_id": vaccine.id, "given": "false"},
        {"vaccine_schedule_id": vaccine.id, "given": True, "given_date": "2026-04-01"},
        {"vaccine_schedule_id": vaccine.id, "given": True, "given_date": "2025-12-31"},
    ]:
        response = client.post(url, json={"items": [item]}, headers=auth_headers(user["token"]))
        assert response.status_code == 400
    assert ChildVaccination.query.filter_by(child_id=child["id"]).count() == 0


def test_valid_update_normalizes_note_and_returns_given_state(client, monkeypatch):
    user, child, vaccine = _setup(client)
    monkeypatch.setattr("routes.children_routes.today_wib", lambda: date(2026, 3, 31))
    response = client.post(
        f"/api/children/{child['id']}/vaccinations",
        json={"items": [{
            "vaccine_schedule_id": vaccine.id,
            "given": True,
            "given_date": "2026-02-05",
            "notes": "  Puskesmas\r\nSudah diverifikasi  ",
        }]},
        headers=auth_headers(user["token"]),
    )
    assert response.status_code == 200
    item = response.get_json()["vaccinations"][0]
    assert item["state"] == "given"
    assert item["given_date"] == "2026-02-05"
    assert item["given_notes"] == "Puskesmas\nSudah diverifikasi"

    unmark = client.post(
        f"/api/children/{child['id']}/vaccinations",
        json={"items": [{"vaccine_schedule_id": vaccine.id, "given": False, "given_date": None}]},
        headers=auth_headers(user["token"]),
    )
    assert unmark.status_code == 200
    cleared = unmark.get_json()["vaccinations"][0]
    assert cleared["given"] is False
    assert cleared["given_date"] is None
    assert cleared["given_notes"] is None
