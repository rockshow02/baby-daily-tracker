from datetime import datetime, timedelta

from extensions import db
from models import IdempotencyKey
from utils.idempotency import cleanup_expired_idempotency_keys
from tests.conftest import auth_headers, create_child, register


def _seed_key(user_id, child_id, endpoint, key, created_at):
    row = IdempotencyKey(
        user_id=user_id,
        child_id=child_id,
        endpoint=endpoint,
        client_request_id=key,
        fingerprint="fp",
        response_status=201,
        response_body={"id": 1},
        created_at=created_at,
    )
    db.session.add(row)
    return row


def test_cleanup_removes_only_expired_records(client, app):
    user = register(client)
    child = create_child(client, user["token"])

    now = datetime.utcnow()
    old_row = _seed_key(user["id"], child["id"], "feeding-logs", "old-key", now - timedelta(days=100))
    recent_row = _seed_key(user["id"], child["id"], "feeding-logs", "recent-key", now - timedelta(days=10))
    db.session.commit()

    cutoff = now - timedelta(days=90)
    deleted = cleanup_expired_idempotency_keys(cutoff)
    db.session.commit()

    assert deleted == 1
    remaining = IdempotencyKey.query.all()
    assert len(remaining) == 1
    assert remaining[0].client_request_id == "recent-key"


def test_cleanup_removes_nothing_when_all_records_are_recent(client, app):
    user = register(client)
    child = create_child(client, user["token"])

    now = datetime.utcnow()
    _seed_key(user["id"], child["id"], "feeding-logs", "recent-key-1", now - timedelta(days=1))
    _seed_key(user["id"], child["id"], "feeding-logs", "recent-key-2", now - timedelta(days=5))
    db.session.commit()

    cutoff = now - timedelta(days=90)
    deleted = cleanup_expired_idempotency_keys(cutoff)
    db.session.commit()

    assert deleted == 0
    assert IdempotencyKey.query.count() == 2
