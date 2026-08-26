from datetime import date, timedelta
from types import SimpleNamespace

from tests.conftest import auth_headers, create_child, register
from utils.development_goal_engine import goal_state
from utils.timezone_utils import today_wib


def test_goal_state_boundaries():
    today=date(2026,8,26)
    assert goal_state(SimpleNamespace(completed_at=None,target_date=today-timedelta(days=1)),today)=="overdue"
    assert goal_state(SimpleNamespace(completed_at=None,target_date=today),today)=="due"
    assert goal_state(SimpleNamespace(completed_at=None,target_date=today+timedelta(days=7)),today)=="due"
    assert goal_state(SimpleNamespace(completed_at=None,target_date=today+timedelta(days=8)),today)=="upcoming"
    assert goal_state(SimpleNamespace(completed_at=object(),target_date=today-timedelta(days=9)),today)=="completed"


def test_goal_crud_complete_and_reopen(client):
    owner=register(client);child=create_child(client,owner["token"]);headers=auth_headers(owner["token"])
    payload={"category":"growth_check","title":"Jadwalkan ukur tinggi","target_date":today_wib().isoformat(),"note":"Bawa buku"}
    created=client.post(f"/api/children/{child['id']}/development-goals",json=payload,headers=headers)
    assert created.status_code==201,created.get_json();goal=created.get_json();assert goal["state"]=="due"
    completed=client.post(f"/api/development-goals/{goal['id']}/complete",headers=headers)
    assert completed.status_code==200 and completed.get_json()["state"]=="completed"
    replay=client.post(f"/api/development-goals/{goal['id']}/complete",headers=headers)
    assert replay.status_code==200
    reopened=client.post(f"/api/development-goals/{goal['id']}/reopen",headers=headers)
    assert reopened.status_code==200 and reopened.get_json()["completed_at"] is None
    updated=client.put(f"/api/development-goals/{goal['id']}",json={"title":"Ukur tinggi di posyandu"},headers=headers)
    assert updated.status_code==200 and updated.get_json()["title"]=="Ukur tinggi di posyandu"
    assert client.delete(f"/api/development-goals/{goal['id']}",headers=headers).status_code==200


def test_goal_validation_and_access(client):
    owner=register(client);child=create_child(client,owner["token"]);headers=auth_headers(owner["token"])
    assert client.post(f"/api/children/{child['id']}/development-goals",json={"category":"weight_target","title":"x","target_date":"2026-08-26"},headers=headers).status_code==400
    assert client.get(f"/api/children/{child['id']}/development-goals",headers={"Authorization":"Bearer invalid"}).status_code==404
