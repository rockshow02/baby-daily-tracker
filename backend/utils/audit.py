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

# Marker generik buat "sesuatu yang privat berubah, tapi APANYA nggak
# disebut" (lihat PRIVATE_CHANGED_FIELDS di bawah) — SATU string tetap
# yang SAMA di semua entity_type, bukan nama field asli manapun, jadi
# nggak pernah bentrok sama nama kolom sungguhan.
PRIVATE_MARKER = "private_details"

# Kebijakan privasi field mutable, 1 SUMBER KEBENARAN per entity_type,
# dibagi 2 kategori yang SALING LEPAS (union keduanya = SEMUA field
# mutable yang route-nya benar-benar bisa diubah lewat PUT):
#
#   SAFE_CHANGED_FIELDS   -> nama field-nya BOLEH disebut apa adanya di
#                            changed_fields (TETAP cuma NAMA-nya, nggak
#                            pernah nilainya) — field struktural/kategori/
#                            angka/waktu yang nyebut "field ini yang
#                            diubah" doang nggak membocorkan konten medis
#                            spesifik anak (mis. timestamp, feed_type,
#                            volume_ml, weight_kg, method, mood).
#   PRIVATE_CHANGED_FIELDS -> field mutable yang SENGAJA nggak pernah
#                            disebut namanya sama sekali — teks bebas
#                            (`notes`, semua Text/String panjang yang
#                            diketik user), atau field yang NAMANYA AJA
#                            udah nunjukin identitas medis spesifik anak
#                            (nama obat, dosis, nama penyakit, gejala,
#                            diagnosis, alasan kunjungan, nama dokter/
#                            klinik). Kalau field di kategori ini yang
#                            berubah, changed_fields CUMA dapet
#                            PRIVATE_MARKER ("private_details") — bukan
#                            nama field aslinya, dan TETAP TIDAK PERNAH
#                            nilainya.
#
# Field di LUAR union kedua dict ini (termasuk key request mentah yang
# nggak dikenal sama sekali, atau field relasi/FK doang) TIDAK PERNAH
# nyampe ke audit trail dalam bentuk APA PUN — bukan cuma nilainya, nama
# ATAUPUN keberadaan perubahannya juga nggak pernah kesebut.
#
# (lihat backend/docs/AUDIT_TRAIL.md buat daftar lengkap entity_type yang
# DIKECUALIKAN total di Phase 1 — profil anak, membership caregiver,
# vaksinasi, profil user, Telegram, backup/restore, login.)
SAFE_CHANGED_FIELDS = {
    "feeding_log": {"timestamp", "feed_type", "duration_minutes", "volume_ml", "breast_side"},
    "sleep_log": {"start_time", "end_time", "sleep_type"},
    "diaper_log": {"timestamp", "diaper_type", "consistency", "color"},
    "pumping_log": {"timestamp", "duration_minutes", "volume_ml", "breast_side"},
    "activity_log": {"timestamp", "activity_type", "duration_minutes"},
    "growth_measurement": {"measured_date", "weight_kg", "height_cm", "head_circumference_cm"},
    "doctor_visit": {"visit_date", "next_visit_date"},
    "temperature_log": {"timestamp", "temperature_celsius", "method"},
    "illness_log": {"start_date", "end_date"},
    "medication_log": {"timestamp"},
    "mood_log": {"timestamp", "mood"},
    "milestone_log": {"milestone_type", "achieved_date"},
    # Care Reminders & Schedules Phase 1 (lihat backend/docs/REMINDERS.md)
    # — field JADWAL/kategori aman disebut namanya; `title` (bisa aja
    # diisi caregiver dengan nama obat/rincian medis, mis. "Kasih
    # Paracetamol") ada di PRIVATE_CHANGED_FIELDS di bawah.
    "reminder": {"reminder_type", "scheduled_at", "recurrence", "is_active"},
    # Medication Schedule & Adherence Phase 1 (lihat
    # backend/docs/MEDICATION_SCHEDULE.md) — CUMA field JADWAL/struktural
    # (kapan, berapa kali sehari, aktif/nggak) yang aman disebut namanya;
    # nama obat & dosis (identitas medis spesifik anak, persis kebijakan
    # `medication_log` di bawah) dan instruksi bebas teks ada di
    # PRIVATE_CHANGED_FIELDS.
    "medication_schedule": {"start_date", "end_date", "times_of_day", "is_active"},
    # Child Medical Profile & Emergency Card Phase 1 (lihat
    # backend/docs/MEDICAL_PROFILE.md) — set KOSONG SENGAJA: TIDAK ADA
    # satu pun field profil medis yang "aman" disebut namanya (bahkan
    # golongan darah TETAP data medis sensitif per requirement eksplisit
    # "treat all of these fields as sensitive medical/private data") --
    # SEMUA field-nya ada di PRIVATE_CHANGED_FIELDS di bawah, entry ini
    # CUMA supaya entity_type-nya lolos allowlist record_audit_event()
    # (SAFE_CHANGED_FIELDS kosong tetap valid, beda dari "entity_type
    # nggak terdaftar sama sekali").
    "medical_profile": set(),
    # Caregiver Handover Summary Phase 1 (lihat
    # backend/docs/CAREGIVER_HANDOVER.md) — SATU-SATUNYA field mutable
    # lewat PUT adalah `note` (catatan serah-terima bebas-teks), yang
    # SENGAJA diperlakukan privat (lihat PRIVATE_CHANGED_FIELDS di
    # bawah) — set KOSONG di sini SAMA PERSIS pola `medical_profile` di
    # atas, CUMA supaya entity_type-nya lolos allowlist
    # record_audit_event() (bukan berarti "tidak ada field yang
    # berubah", field-nya TETAP ada, cuma tidak pernah "aman" disebut
    # namanya).
    "caregiver_handover": set(),
    "memory_journal": {"occurred_date"},
}

PRIVATE_CHANGED_FIELDS = {
    "feeding_log": {"notes"},
    "sleep_log": {"notes"},
    "diaper_log": {"notes"},
    "pumping_log": {"notes"},
    "activity_log": {"notes"},
    "growth_measurement": {"notes"},
    # nama dokter/klinik, alasan kunjungan, dan diagnosis SEMUANYA
    # identitas medis spesifik anak/provider — bukan cuma "diagnosis"
    # doang yang privat, "reason" (keluhan) dan doctor_name/clinic_name
    # (siapa/di mana anak diperiksa) sama sensitifnya.
    "doctor_visit": {"doctor_name", "clinic_name", "reason", "diagnosis", "notes"},
    "temperature_log": {"notes"},
    # illness_name = nama penyakit spesifik anak (setara sensitifnya sama
    # diagnosis di doctor_visit) — CUMA start_date/end_date (kapan mulai/
    # sembuh) yang cukup "struktural" buat aman disebut namanya.
    "illness_log": {"illness_name", "symptoms", "notes"},
    "medication_log": {"medication_name", "dosage", "notes"},
    "mood_log": {"notes"},
    # custom_label = teks bebas yang diketik user (analog sama notes),
    # CUMA relevan kalau milestone_type == 'custom'.
    "milestone_log": {"custom_label", "notes"},
    # title pengingat = teks bebas yang diketik caregiver, BISA aja
    # berisi nama obat/rincian medis spesifik — sama sensitifnya kayak
    # notes di tipe record lain.
    "reminder": {"title"},
    # medication_name/dose_value/dose_unit = identitas medis + dosis
    # spesifik anak (SAMA kebijakannya kayak medication_name/dosage di
    # `medication_log`); instructions = teks bebas caregiver, analog notes.
    "medication_schedule": {"medication_name", "dose_value", "dose_unit", "instructions"},
    # Child Medical Profile & Emergency Card Phase 1 -- SEMUA field
    # (golongan darah, alergi, kondisi medis, nama dokter/klinik,
    # SEMUA nomor telepon & nama kontak, instruksi darurat) sensitif,
    # TIDAK ADA satu pun yang aman disebut namanya -- perubahan field
    # mana pun CUMA tercatat sebagai marker generik `private_details`.
    "medical_profile": {
        "blood_type", "allergies", "conditions",
        "primary_doctor_name", "primary_clinic_name", "primary_clinic_phone",
        "emergency_contact_name", "emergency_contact_relationship", "emergency_contact_phone",
        "emergency_instructions",
    },
    # Caregiver Handover Summary Phase 1 -- `note` bebas-teks (bisa aja
    # berisi rincian perawatan/medis spesifik yang caregiver ketik
    # sendiri, sama sensitifnya kayak `notes` di 12 tipe log lain).
    "caregiver_handover": {"note"},
    "memory_journal": {"caption"},
}

# Urutan TETAP (bukan set) — dipakai buat pesan error yang deterministik
# ("entity_type harus salah satu dari: ...") dan buat frontend allowlist.
ENTITY_TYPES = tuple(SAFE_CHANGED_FIELDS.keys())

# --- Event keamanan membership caregiver (Caregiver Roles & Permissions
# Phase 1, lihat backend/docs/ROLES_PERMISSIONS.md) ---
#
# Entity_type TERPISAH dari 12 tipe record di atas (SENGAJA nggak
# digabung ke SAFE_CHANGED_FIELDS/ENTITY_TYPES — 2 makna yang beda: "12
# tipe record medis anak" vs "1 kejadian keamanan soal SIAPA yang boleh
# akses anak ini", nyampur keduanya bikin allowlist di atas jadi
# ambigu). Ini perluasan MINIMAL & KOMPATIBEL ke skema yang udah ada:
# REUSE 3 ACTIONS yang UDAH ADA (nggak nambah action baru sama sekali)
# — `create` = caregiver diundang, `update` = peran caregiver diubah,
# `delete` = akses caregiver dicabut. `entity_id` = ChildInvite.id (buat
# create/"diundang") ATAU ChildCaregiver.id (buat update/delete —
# "diubah"/"dicabut"), persis pola "id record aslinya" yang sama kayak
# 12 tipe lain.
#
# `changed_fields` SELALU None/kosong buat KETIGANYA — kebijakan Phase 1
# SENGAJA TIDAK PERNAH nyimpen peran lama/baru di audit trail sama
# sekali (beda dari 12 tipe record yang minimal nyimpen NAMA field aman
# yang berubah) — cukup metadata "APA yang kejadian, SIAPA pelakunya
# (actor_user_id), KAPAN" — TIDAK PERNAH email, token undangan, atau
# nilai peran apa pun.
MEMBERSHIP_ENTITY_TYPE = "caregiver_membership"

# --- Aksi okurensi pengingat (Care Reminders & Schedules Phase 1, lihat
# backend/docs/REMINDERS.md) ---
#
# 2 entity_type TERPISAH (BUKAN 1 entity_type + changed_fields=["status"])
# SENGAJA dipilih buat ngebedain selesai vs lewati — nama entity_type
# ITU SENDIRI adalah metadata "jenis kejadian apa ini" (persis kayak
# "mood_log" vs "feeding_log" beda entity_type, BUKAN "value leak"),
# sementara changed_fields di SELURUH modul ini tetap kebijakan KETAT
# "nama field doang, TIDAK PERNAH nilai" — nge-taro status
# completed/skipped literal di dalam changed_fields bakal ngelanggar
# invarian itu. `action` SELALU 'create' buat keduanya (1 baris
# ReminderAction BARU beneran dibikin — konsisten sama makna 'create' di
# 12 tipe record lain), `entity_id` = ReminderAction.id ("id record
# aslinya", pola yang sama), `recorded_at` = occurrence_at (kapan
# JADWAL okurensinya, bukan kapan aksinya dicatat) — dari entity_id ini
# baris `reminder_actions` aslinya (permanen, nggak sensitif) bisa
# ditelusuri balik kalau perlu detail lengkap (reminder_id, occurrence_at,
# acted_by_user_id).
REMINDER_OCCURRENCE_COMPLETED_ENTITY_TYPE = "reminder_occurrence_completed"
REMINDER_OCCURRENCE_SKIPPED_ENTITY_TYPE = "reminder_occurrence_skipped"

# --- Doctor Consultation Workflow — Phase 1 (lihat
# backend/docs/DOCTOR_CONSULTATION.md) ---
#
# CUMA export PDF yang diaudit, BUKAN preview (preview itu baca doang,
# dipanggil berkali-kali tiap section/tanggal di-ganti sebelum caregiver
# mantap — mengaudit itu bakal jadi noise besar tanpa nilai keamanan
# tambahan, mirip kenapa GET /reminders atau GET /insights juga nggak
# diaudit). `action` SELALU 'create' (1 kejadian "PDF ini pernah
# dibuat", bukan mutasi record apa pun). `entity_id` SELALU 0 — TIDAK
# ADA baris database yang jadi acuan PDF ini (laporan konsultasi Phase 1
# SENGAJA nggak pernah disimpan permanen, lihat utils/consultation_pdf.py),
# beda dari 12 tipe record lain yang entity_id-nya id baris asli.
# `changed_fields` SELALU None (masuk NO_FIELD_DIFF_ENTITY_TYPES di
# bawah) — rentang tanggal & section yang dipilih TIDAK disimpan di
# baris audit ini sama sekali (kolom changed_fields_json SECARA
# ARSITEKTUR cuma buat NAMA field yang berubah di event 'update', bukan
# wadah nilai/metadata bebas — menyimpan tanggal/kode section di situ
# bakal melanggar invarian itu, lihat docstring record_audit_event).
DOCTOR_CONSULTATION_PDF_EXPORT_ENTITY_TYPE = "doctor_consultation_pdf_export"

# --- Aksi dosis (Medication Schedule & Adherence Phase 1, lihat
# backend/docs/MEDICATION_SCHEDULE.md) ---
#
# Pola SAMA PERSIS REMINDER_OCCURRENCE_*_ENTITY_TYPE di atas — 2
# entity_type terpisah buat administered vs skipped (nama entity_type-nya
# SENDIRI adalah metadata "jenis kejadian apa", bukan value leak),
# `changed_fields` SELALU None (masuk NO_FIELD_DIFF_ENTITY_TYPES di
# bawah — status administered/skipped TIDAK PERNAH dituliskan sebagai
# "nilai" di changed_fields, itu ngelanggar invarian nama-field-doang).
# `action` SELALU 'create' (1 baris MedicationDoseAction BARU beneran
# dibikin), `entity_id` = MedicationDoseAction.id, `recorded_at` =
# occurrence_at (kapan JADWAL dosisnya, bukan kapan aksinya dicatat) —
# waktu ACTUAL aksinya (acted_at) TETAP tersimpan permanen di baris
# `medication_dose_actions` aslinya, cuma nggak dobel-dicatat di sini.
#
# Kalau dosis ini status='administered', 1 MedicationLog BARU JUGA
# dibikin (endpoint yang SAMA, transaksi yang SAMA) — itu diaudit
# TERPISAH lewat entity_type "medication_log" yang SUDAH ADA (persis
# kebijakan `medication_log` yang sudah ada di SAFE/PRIVATE_CHANGED_FIELDS
# di atas), BUKAN duplikasi di sini.
MEDICATION_DOSE_ADMINISTERED_ENTITY_TYPE = "medication_dose_administered"
MEDICATION_DOSE_SKIPPED_ENTITY_TYPE = "medication_dose_skipped"

# --- Child Medical Profile & Emergency Card Phase 1 (lihat
# backend/docs/MEDICAL_PROFILE.md) ---
#
# "Ditandai sudah diperiksa ulang" DIPISAH dari create/update field
# biasa (`entity_type="medical_profile"` di atas) -- ini KEJADIAN
# ("caregiver ini mengonfirmasi profilnya masih akurat SEKARANG"),
# bukan perubahan NILAI field apa pun (caregiver bisa menandai ulang
# tanpa mengubah satu field pun) -- pola SAMA PERSIS
# REMINDER_OCCURRENCE_*_ENTITY_TYPE. `action` SELALU 'create',
# `entity_id` = ChildMedicalProfile.id, `changed_fields` SELALU None.
MEDICAL_PROFILE_REVIEWED_ENTITY_TYPE = "medical_profile_reviewed"

# Ekspor PDF Kartu Darurat -- pola SAMA PERSIS
# DOCTOR_CONSULTATION_PDF_EXPORT_ENTITY_TYPE: `action` SELALU 'create',
# `entity_id` SELALU 0 (PDF-nya sendiri TIDAK PERNAH disimpan
# permanen), `changed_fields` SELALU None. Isi kartu (golongan darah,
# alergi, kontak, dst) TIDAK PERNAH masuk baris audit ini -- cuma
# kejadian "PDF ini pernah dibuat, oleh siapa, kapan".
EMERGENCY_CARD_PDF_EXPORT_ENTITY_TYPE = "emergency_card_pdf_export"

# --- Caregiver Handover Summary — Phase 1 (lihat
# backend/docs/CAREGIVER_HANDOVER.md) ---
#
# "handover dibuat" DAN "catatan diubah" pakai entity_type
# "caregiver_handover" biasa di atas (action='create'/'update', lewat
# SAFE/PRIVATE_CHANGED_FIELDS seperti 13 tipe record lain). "ditutup"
# dan "diakui/dibaca" adalah KEJADIAN terpisah (pola SAMA PERSIS
# MEDICAL_PROFILE_REVIEWED_ENTITY_TYPE di atas -- bukan perubahan NILAI
# field apa pun), `action` SELALU 'create', `changed_fields` SELALU
# None. `entity_id` = CaregiverHandover.id (buat closed) ATAU
# CaregiverHandoverAcknowledgement.id (buat acknowledged) -- "id record
# aslinya", pola yang sama kayak SELURUH entity_type lain di modul ini.
# TIDAK PERNAH menyimpan isi ringkasan (feeding/tidur/obat/dst) ATAUPUN
# isi `note` di baris audit manapun di sini.
CAREGIVER_HANDOVER_CLOSED_ENTITY_TYPE = "caregiver_handover_closed"
CAREGIVER_HANDOVER_ACKNOWLEDGED_ENTITY_TYPE = "caregiver_handover_acknowledged"
MONTHLY_STORY_PDF_EXPORT_ENTITY_TYPE = "monthly_story_pdf_export"

# Entity_type yang SENGAJA nggak punya entry SAFE_CHANGED_FIELDS sama
# sekali — `changed_fields` buat SEMUANYA SELALU dipaksa None (lihat
# record_audit_event di bawah), TIDAK PEDULI apa pun yang dikirim
# pemanggil.
NO_FIELD_DIFF_ENTITY_TYPES = (
    MEMBERSHIP_ENTITY_TYPE,
    REMINDER_OCCURRENCE_COMPLETED_ENTITY_TYPE,
    REMINDER_OCCURRENCE_SKIPPED_ENTITY_TYPE,
    DOCTOR_CONSULTATION_PDF_EXPORT_ENTITY_TYPE,
    MEDICATION_DOSE_ADMINISTERED_ENTITY_TYPE,
    MEDICATION_DOSE_SKIPPED_ENTITY_TYPE,
    MEDICAL_PROFILE_REVIEWED_ENTITY_TYPE,
    EMERGENCY_CARD_PDF_EXPORT_ENTITY_TYPE,
    CAREGIVER_HANDOVER_CLOSED_ENTITY_TYPE,
    CAREGIVER_HANDOVER_ACKNOWLEDGED_ENTITY_TYPE,
    MONTHLY_STORY_PDF_EXPORT_ENTITY_TYPE,
)

# Dipakai endpoint baca (routes/audit_routes.py) buat validasi query
# param `entity_type` — 13 tipe record (termasuk "reminder") + 3 tipe
# event tanpa field-diff di atas.
ALL_ENTITY_TYPES = ENTITY_TYPES + NO_FIELD_DIFF_ENTITY_TYPES


def _tracked_fields(entity_type):
    """Union field aman + privat buat 1 entity_type — SEMUA field mutable yang di-snapshot buat deteksi perubahan."""
    return SAFE_CHANGED_FIELDS.get(entity_type, set()) | PRIVATE_CHANGED_FIELDS.get(entity_type, set())


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
    docstring modul). `changed_fields` (iterable nama field/marker, CUMA
    relevan buat action='update') disaring SEBELUM disimpan — CUMA nama
    field yang ada di SAFE_CHANGED_FIELDS[entity_type] ATAU literal
    PRIVATE_MARKER yang lolos; apa pun di luar itu (termasuk nama field
    privat aslinya kalau pemanggil kelupaan udah nge-translate ke marker)
    otomatis dibuang diam-diam (bukan error) — LAPISAN PERTAHANAN TERAKHIR
    di sini, di SATU tempat, biar nggak pernah bergantung 100% ke
    pemanggil (diff_snapshots) buat negakin allowlist-nya.

    Raise ValueError kalau `action`/`entity_type` di luar allowlist —
    ini SENGAJA nge-crash keras (bukan diam-diam dilewatin), soalnya
    kesalahan di sini artinya ada bug di kode server sendiri (bukan input
    user), dan mending ketauan pas development/test daripada diam-diam
    nyimpen audit event yang salah kategori.

    `entity_type` di `NO_FIELD_DIFF_ENTITY_TYPES` (`caregiver_membership`,
    `reminder_occurrence_completed`, `reminder_occurrence_skipped`)
    SENGAJA nggak punya entry di SAFE_CHANGED_FIELDS sama sekali —
    `changed_fields` buat entity_type-entity_type ini SELALU dipaksa
    None, TIDAK PEDULI apa pun yang dikirim pemanggil (bukan cuma
    "disaring", kebijakan Phase 1 buat kejadian-kejadian ini emang nggak
    pernah nyimpen nama field apa pun).
    """
    if action not in ACTIONS:
        raise ValueError(f"action tidak valid: {action!r}")
    if entity_type not in SAFE_CHANGED_FIELDS and entity_type not in NO_FIELD_DIFF_ENTITY_TYPES:
        raise ValueError(f"entity_type tidak valid: {entity_type!r}")

    safe_fields = None
    if changed_fields and entity_type in SAFE_CHANGED_FIELDS:
        allowed = SAFE_CHANGED_FIELDS[entity_type]
        safe_names = sorted({f for f in changed_fields if f in allowed})
        has_marker = PRIVATE_MARKER in changed_fields
        combined = safe_names + ([PRIVATE_MARKER] if has_marker else [])
        safe_fields = combined or None

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
    Balikin dict {nama_field: nilai} buat SEMUA field MUTABLE entity_type
    ini (union SAFE_CHANGED_FIELDS + PRIVATE_CHANGED_FIELDS — TERMASUK
    field privat kayak `notes`, bukan cuma yang aman disebut namanya),
    dibaca LANGSUNG dari attribute model SQLAlchemy (bukan dari
    request/JSON) — dipanggil 2x oleh route (SEBELUM dan SESUDAH mutasi
    diterapkan), lalu hasilnya dibandingin lewat diff_snapshots() di
    bawah.

    PENTING: dict yang dibalikin ini BISA berisi nilai privat (isi notes,
    nama obat, dst) buat KEPERLUAN BANDINGAN DI MEMORI DOANG — nggak
    pernah di-log, nggak pernah disimpen ke DB, nggak pernah ikut ke
    response API. diff_snapshots() di bawah cuma pernah balikin NAMA
    field yang beda (buat field privat malah cuma marker generik, bukan
    namanya pun) — TIDAK PERNAH nilai dari dict ini sendiri.

    Sengaja dibandingin ATTRIBUTE-KE-ATTRIBUTE model (bukan
    "before" dari DB vs "after" dari request mentah) — dua-duanya udah
    ke-normalisasi ke tipe kolom yang SAMA PERSIS (mis. sama-sama
    `datetime` naive WIB lewat to_wib_naive(), bukan bandingin `datetime`
    vs string ISO mentah dari JSON), jadi nggak ada risiko keliru
    nganggep "berubah" padahal cuma beda representasi (mis. int 5 vs
    float 5.0, atau 2 string ISO beda offset tapi instant yang sama).
    """
    tracked = _tracked_fields(entity_type)
    return {field: getattr(entity, field, None) for field in tracked}


def diff_snapshots(before, after, entity_type):
    """
    Balikin `changed_fields` siap-simpan dari 2 snapshot snapshot_fields():
    nama field AMAN yang nilainya BENERAN beda (urut alfabet), diikuti
    PRIVATE_MARKER kalau ADA (1 atau lebih) field privat yang juga beneran
    beda — TIDAK PERNAH nama field privat aslinya, TIDAK PERNAH nilainya,
    dan marker-nya CUMA muncul SEKALI biar pun banyak field privat yang
    berubah bareng.

    Field yang nggak disebut di `after` (mis. entity_type nggak dikenal)
    otomatis nggak pernah keitung berubah — balikin [] kalau bener-bener
    nggak ada apa pun yang berubah (no-op semantik, BUKAN cuma "field ini
    disebut di request").
    """
    changed = {field for field, value in after.items() if before.get(field) != value}
    safe_allowed = SAFE_CHANGED_FIELDS.get(entity_type, set())
    private_allowed = PRIVATE_CHANGED_FIELDS.get(entity_type, set())

    result = sorted(f for f in changed if f in safe_allowed)
    if any(f in private_allowed for f in changed):
        result.append(PRIVATE_MARKER)
    return result
