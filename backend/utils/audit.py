"""
Helper transaksional buat CaregiverAuditEvent (Caregiver Audit Trail —
Phase 1). SATU-SATUNYA tempat baris `caregiver_audit_events` dibikin —
route TIDAK PERNAH nge-construct CaregiverAuditEvent(...) langsung,
biar whitelist action/entity_type/changed_fields di bawah ini SELALU
ditegakkan, di SATU tempat, bukan diulang (dan berpotensi kelewat) di
tiap route.

TRANSAKSIONAL: fungsi di sini CUMA `db.session.add(...)` (nggak pernah
`db.session.commit()` sendiri) — pemanggil (route) yang commit, PERSIS di
commit yang sama buat mutasi entity-nya. Ini yang bikin audit event dan
mutasinya ATOMIK: kalau commit gagal/di-rollback, DUA-DUANYA ke-rollback
bareng; nggak pernah ada mutasi entity yang kesimpen TANPA audit event-nya
(atau sebaliknya). SENGAJA TIDAK pakai after_commit/background thread —
lihat backend/docs/AUDIT_TRAIL.md buat penjelasan lengkapnya.
"""
from datetime import date, datetime

from extensions import db
from models import CaregiverAuditEvent

ACTIONS = ("create", "update", "delete")

# Allowlist ketat, 2 lapis:
#   1. Key dict ini = SATU-SATUNYA entity_type yang boleh masuk audit
#      trail Phase 1 (lihat backend/docs/AUDIT_TRAIL.md buat daftar
#      lengkap tipe yang DIKECUALIKAN di Phase 1 — profil anak, membership
#      caregiver, vaksinasi, profil user, Telegram, backup/restore, login).
#   2. Value (set) = nama field yang boleh dicatat SEBAGAI NAMA doang
#      (bukan nilainya) di changed_fields_json pas action='update'. Field
#      apa pun di luar daftar ini (mis. `notes`, `medication_name`,
#      `symptoms`, ID relasi kayak `illness_id`) TIDAK PERNAH nyampe ke
#      audit trail sama sekali — bukan cuma nilainya yang disembunyikan,
#      NAMANYA pun nggak pernah disebut kalau field itu yang berubah.
SAFE_CHANGED_FIELDS = {
    "feeding_log": {"timestamp", "feed_type", "duration_minutes", "volume_ml", "breast_side"},
    "sleep_log": {"start_time", "end_time", "sleep_type"},
    "diaper_log": {"timestamp", "diaper_type", "consistency", "color"},
    "pumping_log": {"timestamp", "duration_minutes", "volume_ml", "breast_side"},
    "activity_log": {"timestamp", "activity_type", "duration_minutes"},
    "growth_measurement": {"measured_date", "weight_kg", "height_cm", "head_circumference_cm"},
    "doctor_visit": {"visit_date", "doctor_name", "clinic_name", "reason", "diagnosis", "next_visit_date"},
    "temperature_log": {"timestamp", "temperature_celsius", "method"},
    "illness_log": {"illness_name", "start_date", "end_date", "symptoms"},
    "medication_log": {"timestamp", "medication_name", "dosage"},
    "mood_log": {"timestamp", "mood"},
    "milestone_log": {"milestone_type", "custom_label", "achieved_date"},
}

# Urutan TETAP (bukan set) — dipakai buat pesan error yang deterministik
# ("entity_type harus salah satu dari: ...") dan buat frontend allowlist.
ENTITY_TYPES = tuple(SAFE_CHANGED_FIELDS.keys())


def _to_recorded_at(value):
    """
    Normalisasi field "waktu kejadian asli" record (mis.
    FeedingLog.timestamp yang udah datetime, ATAU
    GrowthMeasurement.measured_date yang cuma date) jadi datetime yang
    seragam buat disimpan di CaregiverAuditEvent.recorded_at. `date`
    murni (nggak ada info jam) dikonversi ke tengah malam WIB — TETAP
    cuma nyimpen kapan KEJADIANNYA, bukan data medis apa pun yang
    menyertainya.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return None


def record_audit_event(*, child_id, actor_user_id, action, entity_type, entity_id, changed_fields=None, recorded_at=None):
    """
    Tambah 1 CaregiverAuditEvent ke session (BELUM commit — lihat
    docstring modul). `changed_fields` (iterable nama field mentah, CUMA
    relevan buat action='update') disaring lewat SAFE_CHANGED_FIELDS
    SEBELUM disimpan — field yang nggak ada di whitelist entity_type ini
    otomatis dibuang diam-diam (bukan error), biar pemanggil nggak perlu
    mikirin whitelist-nya sendiri-sendiri.

    Raise ValueError kalau `action`/`entity_type` di luar allowlist —
    ini SENGAJA nge-crash keras (bukan diam-diam dilewatin), soalnya
    kesalahan di sini artinya ada bug di kode server sendiri (bukan input
    user), dan mending ketauan pas development/test daripada diam-diam
    nyimpen audit event yang salah kategori.
    """
    if action not in ACTIONS:
        raise ValueError(f"action tidak valid: {action!r}")
    if entity_type not in SAFE_CHANGED_FIELDS:
        raise ValueError(f"entity_type tidak valid: {entity_type!r}")

    safe_fields = None
    if changed_fields:
        allowed = SAFE_CHANGED_FIELDS[entity_type]
        filtered = sorted({f for f in changed_fields if f in allowed})
        safe_fields = filtered or None

    event = CaregiverAuditEvent(
        child_id=child_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        changed_fields_json=safe_fields,
        recorded_at=_to_recorded_at(recorded_at),
    )
    db.session.add(event)
    return event


def snapshot_fields(entity, entity_type):
    """
    Balikin dict {nama_field: nilai} buat SEMUA field di whitelist
    entity_type ini, dibaca LANGSUNG dari attribute model SQLAlchemy
    (bukan dari request/JSON) — dipanggil 2x oleh route (SEBELUM dan
    SESUDAH mutasi diterapkan), lalu hasilnya dibandingin lewat
    diff_snapshots() di bawah.

    Sengaja dibandingin ATTRIBUTE-KE-ATTRIBUTE model (bukan
    "before" dari DB vs "after" dari request mentah) — dua-duanya udah
    ke-normalisasi ke tipe kolom yang SAMA PERSIS (mis. sama-sama
    `datetime`, bukan bandingin `datetime` vs string ISO mentah dari
    JSON), jadi nggak ada risiko keliru nganggep "berubah" padahal cuma
    beda representasi (mis. None vs None tetap keitung sama, bukan
    ke-anggap "field ini disebut di request jadi otomatis dianggap
    berubah").
    """
    allowed = SAFE_CHANGED_FIELDS.get(entity_type, set())
    return {field: getattr(entity, field, None) for field in allowed}


def diff_snapshots(before, after):
    """Nama field (urut alfabet) yang nilainya BENERAN beda antara 2 snapshot dari snapshot_fields()."""
    return sorted(field for field, value in after.items() if before.get(field) != value)
