"""
Helper akses anak. Satu anak bisa diakses oleh beberapa akun (multi-caregiver:
orang tua, ART, dll) — jadi pengecekan "punya akses" bukan lagi Child.user_id
== user_id doang, tapi cek keanggotaan di tabel child_caregivers.
"""
from models import Child, ChildCaregiver


def get_accessible_child(child_id, user_id):
    """Return Child kalau user_id punya akses (owner atau caregiver), else None."""
    if not user_id:
        return None
    return (
        Child.query.join(ChildCaregiver, ChildCaregiver.child_id == Child.id)
        .filter(Child.id == child_id, ChildCaregiver.user_id == user_id)
        .first()
    )


def get_accessible_children(user_id):
    """Semua anak yang bisa diakses user_id (owner atau caregiver), urut dibuat duluan."""
    return (
        Child.query.join(ChildCaregiver, ChildCaregiver.child_id == Child.id)
        .filter(ChildCaregiver.user_id == user_id)
        .order_by(Child.created_at.asc())
        .all()
    )


def get_caregiver_role(child_id, user_id):
    cc = ChildCaregiver.query.filter_by(child_id=child_id, user_id=user_id).first()
    return cc.role if cc else None