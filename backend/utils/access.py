"""
Otorisasi terpusat — akses anak (multi-caregiver) DAN peran (Caregiver
Roles & Permissions Phase 1, lihat backend/docs/ROLES_PERMISSIONS.md).

SATU-SATUNYA tempat "siapa boleh apa" ditentukan — route TIDAK PERNAH
bandingin string role sendiri-sendiri (`if role == "editor"` dst
tersebar di banyak file), route CUMA manggil helper `require_*` di bawah
ini, biar kebijakannya SELALU konsisten di semua endpoint dan gampang
diaudit di 1 tempat.

Model peran:
  - `owner`  — SATU-SATUNYA sumber kebenarannya `Child.user_id` (pembuat
    anak). TIDAK PERNAH direpresentasikan pakai baris `child_caregivers`
    (lihat models.py:ChildCaregiver docstring) — jadi resolve_role() di
    bawah SELALU cek Child.user_id LEBIH DULU sebelum nengok tabel
    child_caregivers sama sekali.
  - `editor` — baris `child_caregivers.role == 'editor'`. Boleh baca,
    bikin, ubah, hapus record BUATAN SENDIRI.
  - `viewer` — baris `child_caregivers.role == 'viewer'`. Boleh baca
    doang, TIDAK PERNAH boleh bikin/ubah/hapus apa pun.

PENTING: role CUMA PERNAH dipercaya dari hasil query DATABASE di sini —
TIDAK PERNAH dari body/header/query-string request klien manapun (klien
nggak pernah "bilang" perannya sendiri ke endpoint mana pun di app ini).
"""
from sqlalchemy import or_

from extensions import db
from models import Child, ChildCaregiver

ROLE_OWNER = "owner"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"

# Nilai yang BOLEH tersimpan literal di ChildCaregiver.role/ChildInvite.role
# (ditegakkan JUGA lewat CHECK constraint DB — lihat models.py) — 'owner'
# SENGAJA TIDAK PERNAH ada di sini, lihat docstring modul.
MEMBERSHIP_ROLES = (ROLE_EDITOR, ROLE_VIEWER)

# Role yang boleh CREATE/UPDATE record anak (Phase 1: 12 tipe log +
# vaksinasi) — viewer TIDAK PERNAH masuk sini.
WRITE_ROLES = (ROLE_OWNER, ROLE_EDITOR)


def resolve_role(child, user_id):
    """
    Balikin 'owner' | 'editor' | 'viewer' | None buat (child, user_id) ini.
    None berarti user_id nggak punya akses SAMA SEKALI ke child ini
    (bukan owner, bukan caregiver terdaftar).
    """
    if not child or not user_id:
        return None
    if child.user_id == user_id:
        return ROLE_OWNER
    cc = ChildCaregiver.query.filter_by(child_id=child.id, user_id=user_id).first()
    return cc.role if cc else None


def get_accessible_child(child_id, user_id):
    """
    Return Child kalau user_id punya akses (owner ATAU caregiver
    editor/viewer terdaftar), else None. Dipakai buat SEMUA endpoint baca
    (dan sebagai langkah pertama endpoint tulis, sebelum cek role-nya
    lebih lanjut lewat require_write_access/require_owner_access).
    """
    if not child_id or not user_id:
        return None
    child = db.session.get(Child, child_id)
    if not child:
        return None
    if child.user_id == user_id:
        return child
    is_member = (
        ChildCaregiver.query.filter_by(child_id=child_id, user_id=user_id).first() is not None
    )
    return child if is_member else None


def get_accessible_children(user_id):
    """Semua anak yang bisa diakses user_id (owner ATAU caregiver), urut dibuat duluan."""
    if not user_id:
        return []
    owned_ids = db.session.query(Child.id).filter(Child.user_id == user_id)
    member_ids = db.session.query(ChildCaregiver.child_id).filter(ChildCaregiver.user_id == user_id)
    return (
        Child.query.filter(or_(Child.id.in_(owned_ids), Child.id.in_(member_ids)))
        .order_by(Child.created_at.asc())
        .all()
    )


def get_caregiver_role(child_id, user_id):
    """
    Kompatibilitas mundur nama fungsi (dipakai beberapa tempat lama) —
    delegasi ke resolve_role() lewat get_accessible_child() biar SELALU
    lewat 1 jalur query yang sama (owner-aware), bukan query terpisah
    yang cuma nengok child_caregivers doang kayak versi sebelumnya (yang
    bakal salah balikin None buat owner sekarang, karena owner nggak
    punya baris di situ lagi).
    """
    if not child_id or not user_id:
        return None
    child = db.session.get(Child, child_id)
    return resolve_role(child, user_id) if child else None


def require_read_access(child_id, user_id):
    """
    (child, role) kalau user_id boleh BACA child_id, else (None, None).
    Semua role (owner/editor/viewer) lolos di sini — baca selalu boleh
    buat siapa pun yang terdaftar, lihat matriks izin di
    backend/docs/ROLES_PERMISSIONS.md.
    """
    child = get_accessible_child(child_id, user_id)
    if not child:
        return None, None
    return child, resolve_role(child, user_id)


def require_write_access(child_id, user_id):
    """(child, role) kalau user_id boleh CREATE/UPDATE record anak ini (owner/editor), else (None, None)."""
    child, role = require_read_access(child_id, user_id)
    if not child or role not in WRITE_ROLES:
        return None, None
    return child, role


def require_owner_access(child_id, user_id):
    """(child, role) kalau user_id ADALAH pemilik anak ini, else (None, None)."""
    child, role = require_read_access(child_id, user_id)
    if not child or role != ROLE_OWNER:
        return None, None
    return child, role


def can_delete_record(role, created_by_user_id, user_id):
    """
    True kalau user_id (dengan `role` di anak ini) boleh menghapus 1
    record dengan `created_by_user_id` tertentu.

    - owner: selalu boleh (record siapa pun, termasuk record legacy yang
      created_by_user_id-nya NULL).
    - editor: CUMA boleh kalau created_by_user_id COCOK PERSIS sama
      user_id-nya sendiri — record legacy (NULL) otomatis GAGAL di sini
      (None == user_id selalu False), bukan pengecualian khusus.
    - viewer (atau role apa pun di luar owner/editor): selalu False.
    """
    if role == ROLE_OWNER:
        return True
    if role == ROLE_EDITOR:
        return created_by_user_id is not None and created_by_user_id == user_id
    return False
