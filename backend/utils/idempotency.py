"""
Helper buat bikin endpoint POST "create log" aman diulang (idempotent).

Dipakai bareng offline queue frontend: klien ngirim header
X-Idempotency-Key yang sama tiap kali request yang sama itu di-retry
(baik retry dari antrian offline, maupun retry pas request pertama yang
online tapi responsnya keputus di tengah jalan). Kalau key yang sama udah
pernah sukses diproses DENGAN DATA YANG SAMA, endpoint ini balikin hasil
yang ORIGINAL, bukan bikin record baru — jadi nggak ada data dobel walau
requestnya dikirim lebih dari sekali. Kalau key yang sama dipakai lagi
tapi datanya BEDA (bug klien, atau key kepake ulang nggak sengaja), itu
ditolak (409) bukan diam-diam dianggap sama.
"""
import hashlib
import json

from flask import current_app
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import IdempotencyKey

CONFLICT_MESSAGE = {
    "error": "Request ini sudah pernah diproses dengan data yang berbeda. Coba lagi dengan permintaan baru.",
}


def compute_fingerprint(payload):
    """
    Hash sha256 dari payload request yang dinormalisasi. Kita SENGAJA cuma
    nyimpen hash-nya (bukan payload mentahnya) di tabel idempotency_keys —
    payload aslinya bisa berisi data kesehatan bayi yang nggak perlu
    disimpan dobel di sana, cukup di baris log-nya sendiri.
    """
    canonical = json.dumps(payload or {}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def idempotent_create(user_id, child_id, endpoint, client_request_id, fingerprint, build, after_commit=None):
    """
    build() harus nge-`db.session.add(...)` instance model baru (TANPA
    commit) dan return `.to_dict()`-nya. Dipanggil paling banyak sekali —
    kalau client_request_id ini udah pernah diproses sebelumnya (dengan
    fingerprint yang cocok), build() nggak dipanggil sama sekali dan hasil
    yang lama langsung dikembalikan.

    after_commit(), kalau dikasih, dipanggil TEPAT SEKALI, HANYA setelah
    commit beneran sukses buat record yang BENERAN BARU (bukan replay,
    bukan yang kalah race) — dipakai buat notifikasi caregiver, biar nggak
    pernah ada notifikasi buat record yang di-rollback atau yang direplay.
    Kegagalan di after_commit() nggak boleh sampai bikin log yang udah
    kesimpen jadi invalid, makanya di-try/except di sini, bukan dibiarin
    nembus ke pemanggil.

    Return (response_body, status_code, is_replay).
    """
    if client_request_id:
        existing = IdempotencyKey.query.filter_by(
            user_id=user_id,
            child_id=child_id,
            endpoint=endpoint,
            client_request_id=client_request_id,
        ).first()
        if existing:
            # fingerprint kosong = baris lama dari sebelum kolom ini ada —
            # nggak bisa dibandingin, jadi di-"grandfather" (dianggap cocok)
            # daripada nolak diam-diam gara-gara data yang emang nggak ada.
            if existing.fingerprint and existing.fingerprint != fingerprint:
                return CONFLICT_MESSAGE, 409, True
            return existing.response_body, existing.response_status, True

    response_body = build()

    if not client_request_id:
        db.session.commit()
        if after_commit:
            _run_after_commit(after_commit, endpoint)
        return response_body, 201, False

    db.session.add(
        IdempotencyKey(
            user_id=user_id,
            child_id=child_id,
            endpoint=endpoint,
            client_request_id=client_request_id,
            fingerprint=fingerprint,
            response_status=201,
            response_body=response_body,
        )
    )
    try:
        db.session.commit()
    except IntegrityError:
        # Request yang sama nyampe dua kali hampir bersamaan (race) — yang
        # ini kalah, SELURUH transaksi (termasuk log yang barusan di-flush)
        # ke-rollback bareng, jadi cuma pemenangnya yang beneran kesimpen.
        # Jangan panggil after_commit di sini — pemenang race yang udah
        # notify duluan.
        db.session.rollback()
        existing = IdempotencyKey.query.filter_by(
            user_id=user_id,
            child_id=child_id,
            endpoint=endpoint,
            client_request_id=client_request_id,
        ).first()
        if existing:
            if existing.fingerprint and existing.fingerprint != fingerprint:
                return CONFLICT_MESSAGE, 409, True
            return existing.response_body, existing.response_status, True
        raise

    if after_commit:
        _run_after_commit(after_commit, endpoint)

    return response_body, 201, False


def _run_after_commit(after_commit, endpoint):
    try:
        after_commit()
    except Exception:
        # SENGAJA nggak nge-log isi exception/pesan notifikasinya — bisa
        # aja kebawa data kesehatan bayi. Cukup tau endpoint mana yang
        # notifikasinya gagal, buat debugging operasional.
        current_app.logger.warning("idempotent_create: after_commit gagal (endpoint=%s)", endpoint)


def cleanup_expired_idempotency_keys(cutoff):
    """
    Hapus baris idempotency_keys yang lebih tua dari `cutoff` (datetime).
    Return jumlah baris yang dihapus. TIDAK commit sendiri — pemanggil
    yang tentuin kapan commit (biar gampang dites/di-dry-run).
    """
    return IdempotencyKey.query.filter(IdempotencyKey.created_at < cutoff).delete()
