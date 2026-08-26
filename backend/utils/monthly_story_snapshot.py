from utils.snapshot_token import (compute_sha256_digest, decode_signed_snapshot_token,
                                  generate_signed_snapshot_token)

SALT = "monthly-story-v1"
VERSION = 1
MAX_AGE_SECONDS = 15 * 60


def story_digest(report):
    return compute_sha256_digest(report)


def generate_story_token(child_id, user_id, preview_at, digest):
    return generate_signed_snapshot_token(salt=SALT, claims={
        "v": VERSION, "child_id": child_id, "user_id": user_id,
        "preview_at": preview_at, "digest": digest,
    })


def decode_story_token(token, child_id, user_id):
    return decode_signed_snapshot_token(token, salt=SALT, max_age_seconds=MAX_AGE_SECONDS,
        expected_schema_version=VERSION, child_id=child_id, user_id=user_id)
