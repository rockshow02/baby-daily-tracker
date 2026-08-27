from datetime import date

from extensions import db
from models import FamilyDevelopmentCheckIn
from tests.conftest import auth_headers, create_child, register


def make_payload(day="2026-09-01"):
    return {"appointment_date":day,"doctor_visit_id":None,
            "checklist":{"health_book":True,"identity_or_insurance":False,
                         "medication_list":False,"test_results":False,"child_supplies":False},
            "questions":["Apa yang perlu dipantau?"],"source_check_in_ids":[]}


def test_preparation_crud_computed_status_and_duplicate(client):
    owner=register(client);child=create_child(client,owner["token"]);headers=auth_headers(owner["token"])
    created=client.post(f"/api/children/{child['id']}/appointment-preparations",json=make_payload(),headers=headers)
    assert created.status_code==201,created.get_json();row=created.get_json()
    assert row["status"]=="in_progress" and row["completed_items"]==1 and row["total_items"]==5
    assert client.post(f"/api/children/{child['id']}/appointment-preparations",json=make_payload(),headers=headers).status_code==409
    changed=make_payload();changed["checklist"]={key:True for key in changed["checklist"]}
    updated=client.put(f"/api/appointment-preparations/{row['id']}",json=changed,headers=headers)
    assert updated.status_code==200 and updated.get_json()["status"]=="ready"
    assert client.delete(f"/api/appointment-preparations/{row['id']}",headers=headers).status_code==200


def test_preparation_can_use_only_flagged_check_in_from_same_child(client,app):
    owner=register(client);child=create_child(client,owner["token"]);headers=auth_headers(owner["token"])
    with app.app_context():
        flagged=FamilyDevelopmentCheckIn(child_id=child["id"],created_by_user_id=owner["id"],period_month=date(2026,8,1),areas={},reflection_note="Bahas pola tidur",discuss_with_professional=True)
        unflagged=FamilyDevelopmentCheckIn(child_id=child["id"],created_by_user_id=owner["id"],period_month=date(2026,7,1),areas={},discuss_with_professional=False)
        db.session.add_all([flagged,unflagged]);db.session.commit();flagged_id=flagged.id;unflagged_id=unflagged.id
    listing=client.get(f"/api/children/{child['id']}/appointment-preparations",headers=headers).get_json()
    assert [item["id"] for item in listing["suggested_check_ins"]]==[flagged_id]
    good=make_payload();good["source_check_in_ids"]=[flagged_id]
    assert client.post(f"/api/children/{child['id']}/appointment-preparations",json=good,headers=headers).status_code==201
    bad=make_payload("2026-09-02");bad["source_check_in_ids"]=[unflagged_id]
    assert client.post(f"/api/children/{child['id']}/appointment-preparations",json=bad,headers=headers).status_code==400


def test_preparation_validation_access_and_private_audit(client):
    owner=register(client);child=create_child(client,owner["token"]);headers=auth_headers(owner["token"])
    invalid=make_payload();invalid["questions"]=["x"]*11
    assert client.post(f"/api/children/{child['id']}/appointment-preparations",json=invalid,headers=headers).status_code==400
    row=client.post(f"/api/children/{child['id']}/appointment-preparations",json=make_payload(),headers=headers).get_json()
    changed=make_payload();changed["questions"]=["RAHASIA_PERTANYAAN_DOKTER"]
    client.put(f"/api/appointment-preparations/{row['id']}",json=changed,headers=headers)
    audit=client.get(f"/api/children/{child['id']}/audit-events",headers=headers).get_json()
    assert "RAHASIA_PERTANYAAN_DOKTER" not in str(audit)
    other=register(client,"Other","other-preparation@example.com")
    assert client.get(f"/api/children/{child['id']}/appointment-preparations",headers=auth_headers(other["token"])).status_code==404
