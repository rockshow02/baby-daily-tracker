from tests.conftest import auth_headers, create_child, register


def payload(month="2026-08"):
    return {"period_month": month, "areas": {"motor": "noticed", "communication": "exploring"},
            "reflection_note": "Senang bermain bersama", "discuss_with_professional": True,
            "linked_goal_id": None}


def test_check_in_crud_and_duplicate_protection(client):
    owner=register(client);child=create_child(client,owner["token"]);headers=auth_headers(owner["token"])
    created=client.post(f"/api/children/{child['id']}/family-development-check-ins",json=payload(),headers=headers)
    assert created.status_code==201,created.get_json();row=created.get_json()
    assert row["areas"]["sleep"]=="not_checked" and row["can_edit"] is True
    assert client.post(f"/api/children/{child['id']}/family-development-check-ins",json=payload(),headers=headers).status_code==409
    changed=payload();changed["reflection_note"]="Catatan baru"
    assert client.put(f"/api/family-development-check-ins/{row['id']}",json=changed,headers=headers).status_code==200
    listed=client.get(f"/api/children/{child['id']}/family-development-check-ins",headers=headers).get_json()
    assert listed["items"][0]["reflection_note"]=="Catatan baru"
    assert "bukan skrining" in listed["disclaimer"]
    assert client.delete(f"/api/family-development-check-ins/{row['id']}",headers=headers).status_code==200


def test_check_in_validation_and_access(client):
    owner=register(client);child=create_child(client,owner["token"]);headers=auth_headers(owner["token"])
    bad=payload("2026/08")
    assert client.post(f"/api/children/{child['id']}/family-development-check-ins",json=bad,headers=headers).status_code==400
    bad=payload();bad["areas"]={"diagnosis":"noticed"}
    assert client.post(f"/api/children/{child['id']}/family-development-check-ins",json=bad,headers=headers).status_code==400
    other=register(client,"Other","other-checkin@example.com")
    assert client.get(f"/api/children/{child['id']}/family-development-check-ins",headers=auth_headers(other["token"])).status_code==404


def test_check_in_does_not_expose_values_in_audit(client):
    owner=register(client);child=create_child(client,owner["token"]);headers=auth_headers(owner["token"])
    row=client.post(f"/api/children/{child['id']}/family-development-check-ins",json=payload(),headers=headers).get_json()
    changed=payload();changed["reflection_note"]="Rahasia audit check-in"
    client.put(f"/api/family-development-check-ins/{row['id']}",json=changed,headers=headers)
    audit=client.get(f"/api/children/{child['id']}/audit-events",headers=headers).get_json()
    assert "Rahasia audit check-in" not in str(audit)
    assert any("private_details" in (event.get("changed_fields") or []) for event in audit["events"])
