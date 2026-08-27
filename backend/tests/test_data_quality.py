from datetime import datetime,timedelta

from extensions import db
from models import FeedingLog,MedicationLog,SleepLog
from tests.conftest import auth_headers,create_child,register

NOW=datetime(2026,8,27,10,0)


def setup_data(client,app,monkeypatch):
    owner=register(client);child=create_child(client,owner["token"]);headers=auth_headers(owner["token"])
    monkeypatch.setattr("routes.data_quality_routes.now_wib",lambda:NOW)
    with app.app_context():
        shared=NOW-timedelta(days=1)
        db.session.add_all([
            FeedingLog(child_id=child["id"],created_by_user_id=owner["id"],timestamp=shared,feed_type="sufor",volume_ml=None),
            FeedingLog(child_id=child["id"],created_by_user_id=owner["id"],timestamp=shared,feed_type="sufor",volume_ml=None),
            SleepLog(child_id=child["id"],created_by_user_id=owner["id"],start_time=NOW-timedelta(days=2),end_time=None,sleep_type="malam"),
            MedicationLog(child_id=child["id"],created_by_user_id=owner["id"],timestamp=NOW+timedelta(hours=2),medication_name="RAHASIA_OBAT",dosage=None),
        ]);db.session.commit()
    return owner,child,headers


def test_quality_finds_bounded_generic_issues(client,app,monkeypatch):
    _,child,headers=setup_data(client,app,monkeypatch)
    response=client.get(f"/api/children/{child['id']}/data-quality?days=30",headers=headers)
    assert response.status_code==200;payload=response.get_json()
    categories={item["category"] for item in payload["items"]}
    assert categories=={"duplicate","incomplete","future"}
    assert any(item["record_type"]=="feeding" and len(item["source_ids"])==2 for item in payload["items"] if item["category"]=="duplicate")
    assert any(item["record_type"]=="sleep" for item in payload["items"] if item["category"]=="incomplete")
    assert "RAHASIA_OBAT" not in str(payload)
    assert "bukan penilaian kesehatan" in payload["disclaimer"]


def test_quality_filters_and_validates_parameters(client,app,monkeypatch):
    _,child,headers=setup_data(client,app,monkeypatch)
    filtered=client.get(f"/api/children/{child['id']}/data-quality?days=7&categories=duplicate",headers=headers)
    assert filtered.status_code==200 and all(x["category"]=="duplicate" for x in filtered.get_json()["items"])
    assert client.get(f"/api/children/{child['id']}/data-quality?days=365",headers=headers).status_code==400
    assert client.get(f"/api/children/{child['id']}/data-quality?days=30&categories=diagnosis",headers=headers).status_code==400


def test_quality_requires_child_access(client,app,monkeypatch):
    _,child,_=setup_data(client,app,monkeypatch);other=register(client,"Other","quality-other@example.com")
    response=client.get(f"/api/children/{child['id']}/data-quality?days=30",headers=auth_headers(other["token"]))
    assert response.status_code==404
