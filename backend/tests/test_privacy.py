from extensions import db
from models import Child, ChildCaregiver, User
from tests.conftest import auth_headers, create_child, register


def _invite_and_join(client, owner_token, child_id, member_token, role="viewer"):
    invitation = client.post(
        f"/api/children/{child_id}/invite",
        json={"role": role}, headers=auth_headers(owner_token),
    ).get_json()
    response = client.post(
        "/api/children/join", json={"code": invitation["code"]},
        headers=auth_headers(member_token),
    )
    assert response.status_code == 201


def test_overview_requires_login(client):
    assert client.get("/api/privacy/overview").status_code == 401


def test_overview_returns_counts_and_server_capabilities(client):
    owner = register(client)
    child = create_child(client, owner["token"], name="Nara")
    client.post(
        f"/api/children/{child['id']}/feeding-logs",
        json={"feed_type": "sufor", "volume_ml": 60},
        headers=auth_headers(owner["token"]),
    )
    response = client.get("/api/privacy/overview", headers=auth_headers(owner["token"]))
    assert response.status_code == 200
    data = response.get_json()
    entry = data["children"][0]
    assert entry["child"] == {"id": child["id"], "name": "Nara", "nickname": None, "role": "owner"}
    assert entry["capabilities"] == {"can_export": True, "can_delete_child": True, "can_leave_child": False}
    assert next(item for item in entry["record_groups"] if item["key"] == "feeding_logs")["count"] == 1
    assert entry["total_records"] >= 1
    assert data["account"]["owned_children"] == 1
    assert data["account"]["can_delete_account"] is False


def test_viewer_can_leave_only_with_password_and_exact_child_name(client):
    owner = register(client, email="owner-privacy@example.com")
    member = register(client, email="viewer-privacy@example.com")
    child = create_child(client, owner["token"], name="Nara Putri")
    _invite_and_join(client, owner["token"], child["id"], member["token"])

    wrong = client.post(
        f"/api/privacy/children/{child['id']}/leave",
        json={"password": "wrong", "confirmation": "Nara Putri"},
        headers=auth_headers(member["token"]),
    )
    assert wrong.status_code == 400
    assert ChildCaregiver.query.filter_by(child_id=child["id"], user_id=member["id"]).count() == 1

    ok = client.post(
        f"/api/privacy/children/{child['id']}/leave",
        json={"password": "password123", "confirmation": "Nara Putri"},
        headers=auth_headers(member["token"]),
    )
    assert ok.status_code == 200
    assert ChildCaregiver.query.filter_by(child_id=child["id"], user_id=member["id"]).count() == 0
    assert client.get(f"/api/children/{child['id']}", headers=auth_headers(member["token"])).status_code == 404


def test_owner_cannot_leave_and_viewer_cannot_delete(client):
    owner = register(client, email="owner2-privacy@example.com")
    member = register(client, email="viewer2-privacy@example.com")
    child = create_child(client, owner["token"])
    _invite_and_join(client, owner["token"], child["id"], member["token"])
    payload = {"password": "password123", "confirmation": child["name"]}
    assert client.post(f"/api/privacy/children/{child['id']}/leave", json=payload, headers=auth_headers(owner["token"])).status_code == 400
    assert client.post(f"/api/privacy/children/{child['id']}/delete", json=payload, headers=auth_headers(member["token"])).status_code == 403


def test_child_delete_requires_confirmation_and_removes_database_then_photo(client, monkeypatch):
    import routes.privacy_routes as privacy_routes

    owner = register(client, email="delete-privacy@example.com")
    child = create_child(client, owner["token"], name="Nara")
    row = Child.query.get(child["id"])
    row.photo_filename = "safe-photo.jpg"
    db.session.commit()
    class FakePhoto:
        exists = True
        def unlink(self, missing_ok=False):
            self.exists = False
    photo = FakePhoto()
    monkeypatch.setattr(privacy_routes, "_validated_photo_path", lambda filename: photo)

    wrong = client.post(
        f"/api/privacy/children/{child['id']}/delete",
        json={"password": "password123", "confirmation": "nara"},
        headers=auth_headers(owner["token"]),
    )
    assert wrong.status_code == 400
    assert Child.query.get(child["id"]) is not None
    assert photo.exists is True

    ok = client.post(
        f"/api/privacy/children/{child['id']}/delete",
        json={"password": "password123", "confirmation": "Nara"},
        headers=auth_headers(owner["token"]),
    )
    assert ok.status_code == 200
    assert ok.get_json()["file_cleanup"] == "ok"
    assert Child.query.get(child["id"]) is None
    assert photo.exists is False


def test_invalid_photo_path_does_not_delete_outside_file(client, monkeypatch):
    import routes.privacy_routes as privacy_routes

    owner = register(client, email="unsafe-photo-privacy@example.com")
    child = create_child(client, owner["token"], name="Nara")
    row = Child.query.get(child["id"])
    row.photo_filename = "../outside.jpg"
    db.session.commit()
    monkeypatch.setattr(privacy_routes, "_validated_photo_path", lambda filename: None)
    response = client.post(
        f"/api/privacy/children/{child['id']}/delete",
        json={"password": "password123", "confirmation": "Nara"},
        headers=auth_headers(owner["token"]),
    )
    assert response.status_code == 200
    assert response.get_json()["file_cleanup"] == "warning"
    assert Child.query.get(child["id"]) is None


def test_legacy_unconfirmed_child_delete_is_disabled(client):
    owner = register(client, email="legacy-delete-privacy@example.com")
    child = create_child(client, owner["token"])
    response = client.delete(f"/api/children/{child['id']}", headers=auth_headers(owner["token"]))
    assert response.status_code == 400
    assert Child.query.get(child["id"]) is not None


def test_account_delete_blocked_while_user_owns_child(client):
    user = register(client, email="owned-account-privacy@example.com")
    create_child(client, user["token"])
    response = client.post(
        "/api/privacy/account/delete",
        json={"password": "password123", "confirmation": "HAPUS AKUN"},
        headers=auth_headers(user["token"]),
    )
    assert response.status_code == 409
    assert User.query.get(user["id"]).is_active is True


def test_account_delete_erases_identity_revokes_token_and_removes_membership(client):
    owner = register(client, email="foreign-owner-privacy@example.com")
    user = register(client, name="Sensitive Name", email="erase-me@example.com")
    child = create_child(client, owner["token"])
    _invite_and_join(client, owner["token"], child["id"], user["token"], role="editor")

    response = client.post(
        "/api/privacy/account/delete",
        json={"password": "password123", "confirmation": "HAPUS AKUN"},
        headers=auth_headers(user["token"]),
    )
    assert response.status_code == 200
    erased = User.query.get(user["id"])
    assert erased.is_active is False
    assert erased.name == "Akun dihapus"
    assert erased.email.endswith("@invalid.local")
    assert erased.telegram_chat_id is None
    assert ChildCaregiver.query.filter_by(user_id=user["id"]).count() == 0
    assert client.get("/api/auth/me", headers=auth_headers(user["token"])).status_code == 401
    assert client.post("/api/auth/login", json={"email": "erase-me@example.com", "password": "password123"}).status_code == 401


def test_account_delete_commit_failure_rolls_back_identity_and_membership(client, monkeypatch):
    from sqlalchemy.orm import Session

    owner = register(client, email="rollback-owner-privacy@example.com")
    user = register(client, name="Keep Me", email="rollback-me@example.com")
    child = create_child(client, owner["token"])
    _invite_and_join(client, owner["token"], child["id"], user["token"], role="editor")

    def fail_commit(_session):
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post(
        "/api/privacy/account/delete",
        json={"password": "password123", "confirmation": "HAPUS AKUN"},
        headers=auth_headers(user["token"]),
    )
    assert response.status_code == 500
    unchanged = db.session.get(User, user["id"])
    assert unchanged.is_active is True
    assert unchanged.name == "Keep Me"
    assert unchanged.email == "rollback-me@example.com"
    assert ChildCaregiver.query.filter_by(child_id=child["id"], user_id=user["id"]).count() == 1


def test_confirmation_body_limit(client):
    user = register(client, email="body-limit-privacy@example.com")
    response = client.post(
        "/api/privacy/account/delete",
        data=b"{" + (b"x" * 9000) + b"}",
        content_type="application/json",
        headers=auth_headers(user["token"]),
    )
    assert response.status_code == 413


def test_confirmation_body_limit_without_content_length(app, client):
    """Chunked/missing-length requests cannot bypass the 8 KiB endpoint limit."""
    from io import BytesIO
    from werkzeug.test import EnvironBuilder

    user = register(client, email="missing-length-privacy@example.com")
    payload = b"{" + (b"x" * 9000) + b"}"
    builder = EnvironBuilder(
        path="/api/privacy/account/delete", method="POST",
        input_stream=BytesIO(payload), content_type="application/json",
        headers=auth_headers(user["token"]),
    )
    environ = builder.get_environ()
    environ.pop("CONTENT_LENGTH", None)
    environ["wsgi.input_terminated"] = True
    response = app.response_class.from_app(app.wsgi_app, environ)
    assert response.status_code == 413
