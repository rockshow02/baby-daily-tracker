from datetime import date,datetime

from extensions import db
from models import DevelopmentGoal,FamilyDevelopmentCheckIn,FeedingLog,MemoryJournalEntry
from tests.conftest import auth_headers,create_child,register


def test_monthly_review_aggregates_current_and_previous_without_judgment(client,app):
    owner=register(client);child=create_child(client,owner["token"]);headers=auth_headers(owner["token"])
    with app.app_context():
        db.session.add_all([
          FeedingLog(child_id=child["id"],created_by_user_id=owner["id"],timestamp=datetime(2026,8,10,8),feed_type="asi_langsung"),
          FeedingLog(child_id=child["id"],created_by_user_id=owner["id"],timestamp=datetime(2026,7,10,8),feed_type="asi_langsung"),
          FeedingLog(child_id=child["id"],created_by_user_id=owner["id"],timestamp=datetime(2026,7,11,8),feed_type="asi_langsung"),
          MemoryJournalEntry(child_id=child["id"],created_by_user_id=owner["id"],occurred_date=date(2026,8,12),caption="RAHASIA_CAPTION",photo_filename="review.webp",photo_size_bytes=1,photo_width=1,photo_height=1),
          DevelopmentGoal(child_id=child["id"],created_by_user_id=owner["id"],category="routine",title="RAHASIA_GOAL",target_date=date(2026,8,20),completed_at=datetime(2026,8,18)),
          FamilyDevelopmentCheckIn(child_id=child["id"],created_by_user_id=owner["id"],period_month=date(2026,8,1),areas={},reflection_note="RAHASIA_CHECKIN",discuss_with_professional=True),
        ]);db.session.commit()
    response=client.get(f"/api/children/{child['id']}/family-monthly-review?month=2026-08",headers=headers)
    assert response.status_code==200;payload=response.get_json()
    assert payload["summary"]["care_records"]["feeding"]==1
    assert payload["comparison"]["care_records.feeding"]=={"current":1,"previous":2,"difference":-1}
    assert payload["summary"]["development"]["memories"]==1
    assert payload["summary"]["family"]=={"check_ins":1,"discussion_flags":1,"goals_total":1,"goals_completed":1}
    assert payload["has_family_review"] is True
    serialized=str(payload)
    assert "RAHASIA_CAPTION" not in serialized and "RAHASIA_GOAL" not in serialized and "RAHASIA_CHECKIN" not in serialized
    assert "bukan perubahan kondisi" in payload["disclaimer"]


def test_monthly_review_validation_and_access(client):
    owner=register(client);child=create_child(client,owner["token"]);headers=auth_headers(owner["token"])
    assert client.get(f"/api/children/{child['id']}/family-monthly-review?month=August",headers=headers).status_code==400
    other=register(client,"Other","monthly-review-other@example.com")
    assert client.get(f"/api/children/{child['id']}/family-monthly-review?month=2026-08",headers=auth_headers(other["token"])).status_code==404
