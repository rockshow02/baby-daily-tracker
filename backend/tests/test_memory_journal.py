from io import BytesIO

from PIL import Image

from tests.conftest import auth_headers, create_child, register


def _photo(size=(2400, 1800), fmt="JPEG"):
    output = BytesIO()
    Image.new("RGB", size, (240, 160, 120)).save(output, format=fmt)
    output.seek(0)
    return output


def test_memory_journal_crud_compresses_and_protects_photo(client, app, tmp_path):
    app.config["MEMORY_JOURNAL_UPLOAD_DIR"] = str(tmp_path / "memory")
    owner = register(client)
    child = create_child(client, owner["token"])
    headers = auth_headers(owner["token"])

    created = client.post(
        f"/api/children/{child['id']}/memory-journal",
        data={"occurred_date": "2026-08-20", "caption": "Senyum pertama",
              "photo": (_photo(), "large.jpg")},
        headers=headers, content_type="multipart/form-data",
    )
    assert created.status_code == 201, created.get_json()
    item = created.get_json()
    assert item["caption"] == "Senyum pertama"
    assert max(item["photo_width"], item["photo_height"]) <= 1600
    assert item["photo_size_bytes"] < 2 * 1024 * 1024
    assert "photo_filename" not in item

    listed = client.get(f"/api/children/{child['id']}/memory-journal", headers=headers)
    assert listed.status_code == 200
    assert listed.get_json()["items"][0]["can_delete"] is True
    assert client.get(f"/api/memory-journal/{item['id']}/photo",
                      headers={"Authorization": "Bearer invalid"}).status_code == 404
    photo = client.get(f"/api/memory-journal/{item['id']}/photo", headers=headers)
    assert photo.status_code == 200
    assert photo.content_type == "image/webp"
    photo.close()

    updated = client.put(f"/api/memory-journal/{item['id']}",
        json={"caption": "Hari yang cerah"}, headers=headers)
    assert updated.status_code == 200
    assert updated.get_json()["caption"] == "Hari yang cerah"
    assert client.delete(f"/api/memory-journal/{item['id']}", headers=headers).status_code == 200
    assert not list((tmp_path / "memory").glob("*.webp"))


def test_memory_journal_rejects_invalid_image_and_future_date(client, app, tmp_path):
    app.config["MEMORY_JOURNAL_UPLOAD_DIR"] = str(tmp_path / "memory")
    owner = register(client)
    child = create_child(client, owner["token"])
    headers = auth_headers(owner["token"])
    invalid = client.post(f"/api/children/{child['id']}/memory-journal",
        data={"occurred_date": "2026-08-20", "photo": (BytesIO(b"not-image"), "fake.jpg")},
        headers=headers, content_type="multipart/form-data")
    assert invalid.status_code == 400
    future = client.post(f"/api/children/{child['id']}/memory-journal",
        data={"occurred_date": "2999-01-01", "photo": (_photo((20, 20)), "x.jpg")},
        headers=headers, content_type="multipart/form-data")
    assert future.status_code == 400
    assert not list((tmp_path / "memory").glob("*")) if (tmp_path / "memory").exists() else True
