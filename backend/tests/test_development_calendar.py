from datetime import date, datetime

from tests.conftest import auth_headers, create_child, register
from extensions import db
from models import (DevelopmentGoal, DoctorVisitLog, MedicationSchedule,
                    MemoryJournalEntry, Reminder)


def _setup(client):
    auth = register(client)
    child = create_child(client, auth["token"])
    return auth_headers(auth["token"]), child["id"], auth["id"]


def test_calendar_combines_month_events_and_redacts_medical_text(client, app):
    headers, child_id, user_id = _setup(client)
    with app.app_context():
        db.session.add_all([
            MemoryJournalEntry(child_id=child_id, created_by_user_id=user_id,
                occurred_date=date(2026, 8, 4), caption="Main di taman",
                photo_filename="calendar-test.webp", photo_size_bytes=10,
                photo_width=10, photo_height=10),
            DevelopmentGoal(child_id=child_id, created_by_user_id=user_id,
                category="routine", title="Latihan tengkurap", target_date=date(2026, 8, 6)),
            DoctorVisitLog(child_id=child_id, visit_date=date(2026, 8, 8),
                doctor_name="Dokter Rahasia", clinic_name="Klinik Rahasia",
                diagnosis="Diagnosis Rahasia", reason="Gejala Rahasia", notes="Catatan Rahasia",
                next_visit_date=date(2026, 8, 20), created_by_user_id=user_id),
            Reminder(child_id=child_id, created_by_user_id=user_id, reminder_type="medication",
                title="Rahasia Paracetamol", scheduled_at=datetime(2026, 8, 10, 8), recurrence="daily"),
            MedicationSchedule(child_id=child_id, created_by_user_id=user_id,
                medication_name="Obat Sangat Rahasia", instructions="Instruksi Rahasia",
                start_date=date(2026, 8, 12), end_date=date(2026, 8, 13),
                times_of_day=["08:00", "20:00"], timezone="Asia/Jakarta"),
        ])
        db.session.commit()
    response = client.get(f"/api/children/{child_id}/development-calendar?month=2026-08", headers=headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["month_start"] == "2026-08-01"
    assert payload["month_end"] == "2026-08-31"
    assert any(item["title"] == "Main di taman" for item in payload["items"])
    assert any(item["title"] == "Latihan tengkurap" for item in payload["items"])
    assert any(item["title"] == "Kontrol dokter terjadwal" and item["date"] == "2026-08-20" for item in payload["items"])
    medication = next(item for item in payload["items"] if item["type"] == "medication")
    assert medication["summary"] == "2 waktu pemberian terjadwal"
    serialized = str(payload)
    for secret in ("Paracetamol", "Obat Sangat Rahasia", "Instruksi Rahasia",
                   "Dokter Rahasia", "Klinik Rahasia", "Diagnosis Rahasia",
                   "Gejala Rahasia", "Catatan Rahasia"):
        assert secret not in serialized


def test_calendar_is_month_scoped_and_category_filtered(client, app):
    headers, child_id, user_id = _setup(client)
    with app.app_context():
        db.session.add_all([
            DevelopmentGoal(child_id=child_id, created_by_user_id=user_id, category="custom",
                            title="Agustus", target_date=date(2026, 8, 31)),
            DevelopmentGoal(child_id=child_id, created_by_user_id=user_id, category="custom",
                            title="September", target_date=date(2026, 9, 1)),
        ]); db.session.commit()
    response = client.get(f"/api/children/{child_id}/development-calendar?month=2026-08&categories=goal", headers=headers)
    assert response.status_code == 200
    assert [item["title"] for item in response.get_json()["items"]] == ["Agustus"]
    assert response.get_json()["categories"] == ["goal"]


def test_calendar_rejects_invalid_parameters_and_inaccessible_child(client):
    headers, child_id, _ = _setup(client)
    assert client.get(f"/api/children/{child_id}/development-calendar?month=August", headers=headers).status_code == 400
    assert client.get(f"/api/children/{child_id}/development-calendar?month=2026-08&categories=diagnosis", headers=headers).status_code == 400
    other = register(client, "Other", "other-calendar@example.com")
    assert client.get(f"/api/children/{child_id}/development-calendar?month=2026-08",
                      headers=auth_headers(other["token"])).status_code == 404
