from io import BytesIO

from PIL import Image

from tests.conftest import auth_headers, create_child, register


def _noisy_photo():
    image = Image.effect_noise((900, 900), 90).convert("RGB")
    output = BytesIO(); image.save(output, "JPEG", quality=95); output.seek(0); return output


def _create_entry(client, child_id, headers):
    response = client.post(f"/api/children/{child_id}/memory-journal",
        data={"occurred_date": "2026-08-20", "caption": "Foto besar",
              "photo": (_noisy_photo(), "photo.jpg")}, headers=headers,
        content_type="multipart/form-data")
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def test_storage_overview_optimize_and_safe_orphan_cleanup(client, app, tmp_path):
    root = tmp_path / "memory"; app.config["MEMORY_JOURNAL_UPLOAD_DIR"] = str(root)
    app.config["MEMORY_JOURNAL_WARNING_BYTES"] = 1
    owner = register(client); child = create_child(client, owner["token"]); headers = auth_headers(owner["token"])
    entry = _create_entry(client, child["id"], headers)
    orphan = root / f"memory_{child['id']}_{'a'*32}.webp"; orphan.write_bytes(b"orphan")
    unrelated = root / "do-not-touch.txt"; unrelated.write_text("safe")

    overview = client.get(f"/api/children/{child['id']}/memory-storage", headers=headers)
    assert overview.status_code == 200
    data = overview.get_json()
    assert data["photo_count"] == 1 and data["orphan_file_count"] == 1
    assert data["warning"] is True and data["largest"][0]["id"] == entry["id"]

    optimized = client.post(f"/api/children/{child['id']}/memory-storage/{entry['id']}/optimize", headers=headers)
    assert optimized.status_code == 200
    assert optimized.get_json()["after_bytes"] <= optimized.get_json()["before_bytes"]

    dry = client.post(f"/api/children/{child['id']}/memory-storage/cleanup",
        json={"apply": False}, headers=headers)
    assert dry.status_code == 200 and dry.get_json()["deleted_count"] == 0
    assert orphan.exists()
    rejected = client.post(f"/api/children/{child['id']}/memory-storage/cleanup",
        json={"apply": True, "confirmation": "salah"}, headers=headers)
    assert rejected.status_code == 400 and orphan.exists()
    applied = client.post(f"/api/children/{child['id']}/memory-storage/cleanup",
        json={"apply": True, "confirmation": "BERSIHKAN"}, headers=headers)
    assert applied.status_code == 200 and applied.get_json()["deleted_count"] == 1
    assert not orphan.exists() and unrelated.exists()


def test_storage_is_owner_only_and_entry_must_belong_to_child(client, app, tmp_path):
    app.config["MEMORY_JOURNAL_UPLOAD_DIR"] = str(tmp_path / "memory")
    owner = register(client); child = create_child(client, owner["token"]); headers = auth_headers(owner["token"])
    assert client.get(f"/api/children/{child['id']}/memory-storage",
        headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.post(f"/api/children/{child['id']}/memory-storage/999/optimize", headers=headers).status_code == 404
