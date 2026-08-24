"""
Child Medical Profile & Emergency Card — konsistensi snapshot
preview -> PDF (bug review Agustus 2026, lihat backend/docs/MEDICAL_PROFILE.md
bagian "Konsistensi snapshot preview -> PDF (token bertanda tangan)").

DEFECT yang diperbaiki: endpoint PDF SEBELUMNYA nge-query ulang profil +
jadwal obat TERKINI saat request PDF datang -- kalau caregiver LAIN
mengedit/mereview profil, ATAUPUN jadwal obat dibuat/diubah/nonaktif di
antara waktu preview & unduh PDF, PDF yang dihasilkan bisa BEDA dari apa
yang caregiver SUDAH lihat di preview & konfirmasi privasinya --
`editGenerationRef` di frontend CUMA mendeteksi edit lewat instance
frontend yang SAMA, TIDAK PERNAH melindungi dari perubahan EKSTERNAL.

SOLUSI (arsitektur STATELESS, TETAP kompatibel PythonAnywhere Free --
TIDAK ADA Redis/Celery/worker/cron/cache server lintas-request/tabel DB
baru buat state sementara):

  1. Endpoint preview men-sample `now_wib()` SEKALI, membangun ringkasan
     kartu (utils/emergency_card_report.py:build_emergency_card_summary),
     menghitung digest kriptografis dari REPRESENTASI KANONIK ringkasan
     itu (`canonicalize_emergency_card_report` + `digest_emergency_card_report`
     di bawah), lalu menandatangani TOKEN OPAQUE (`generate_snapshot_token`)
     yang CUMA berisi child_id, user_id, timestamp preview, digest, dan
     versi skema -- TIDAK PERNAH nilai medis/kontak apa pun. Token
     dikembalikan ke frontend BERSAMA hasil preview (field `snapshot_token`).
  2. Endpoint PDF WAJIB menerima token itu balik di body JSON. Token
     diverifikasi (tanda tangan + kedaluwarsa + child/user COCOK), lalu
     ringkasan kartu DIBANGUN ULANG memakai `preview_at` YANG SAMA PERSIS
     dari token (BUKAN `now_wib()` baru) -- ini yang membuat
     `generated_at`/usia/pilihan obat rutin aktif ikut IDENTIK, TANPA
     perlu menyimpan report itu sendiri di mana pun. Digest ringkasan
     yang BARU DIBANGUN ULANG ini dibandingkan (timing-safe) dengan
     digest YANG TERSIMPAN DI DALAM TOKEN -- kalau BEDA (berarti data
     APA PUN yang memengaruhi kartu ini SUDAH berubah sejak preview),
     PDF DITOLAK `409` dengan pesan Indonesia yang aman, TIDAK PERNAH
     merender PDF yang berbeda dari yang sudah di-preview & dikonfirmasi.

TIDAK ADA state disimpan di server ANTARA preview & PDF -- token ITU
SENDIRI yang membawa semua yang dibutuhkan (ditandatangani, jadi TIDAK
BISA dipalsukan klien), persis prinsip "tanpa background/state
persisten" yang ditegakkan di seluruh app ini.
"""
import hashlib
import hmac
import json

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

# Salt TERPISAH dari token login (utils/auth.py:generate_token) -- dua
# jenis token ini SENGAJA tidak bisa saling dipakai silang (salt beda
# -> kunci turunan HMAC-nya beda), walau SECRET_KEY dasarnya sama persis
# (requirement: "Use the existing Flask SECRET_KEY with a standard
# signed serializer already available through Flask/itsdangerous. Do
# not invent custom cryptography").
SNAPSHOT_TOKEN_SALT = "emergency-card-snapshot-v1"

# 15 menit -- cukup buat caregiver baca preview & putuskan unduh PDF,
# TIDAK selama itu sampai jadi risiko token lama disalahgunakan/dipakai
# ulang buat konten yang sudah lama tidak relevan (requirement: "short
# expiry, preferably 10-15 minutes").
SNAPSHOT_TOKEN_MAX_AGE_SECONDS = 15 * 60

# Dibiarkan bisa berubah independen dari CURRENT_MEDICAL_PROFILE_VERSION
# (utils/medical_profile_engine.py, versi SKEMA DATA profil) -- ini versi
# BENTUK KANONIK/token snapshot ini sendiri. Menaikkan angka ini bikin
# SEMUA token lama (skema lama) otomatis ditolak sebagai tidak valid
# (lihat decode_snapshot_token) tanpa perlu logic migrasi token apa pun
# -- token cuma hidup <=15 menit, jadi "downtime" penolakan sesaat
# setelah deploy versi baru TIDAK PERNAH jadi masalah praktis.
EMERGENCY_CARD_SNAPSHOT_SCHEMA_VERSION = 1


class SnapshotTokenError(ValueError):
    """Basis error token snapshot Kartu Darurat -- TIDAK PERNAH di-raise langsung, lihat 2 subclass di bawah."""


class SnapshotTokenInvalidError(SnapshotTokenError):
    """Token hilang/rusak/tanda tangan salah/kedaluwarsa/versi skema tidak cocok -- caller balas 400 (bukan 409 -- ini BUKAN kasus 'data berubah', tokennya sendiri yang tidak bisa dipercaya lagi)."""


class SnapshotTokenUnauthorizedError(SnapshotTokenError):
    """Token SAH (tanda tangan & masa berlaku valid) TAPI diterbitkan buat anak/pengguna LAIN -- caller balas 403 (requirement: 'Confirm the token belongs to the same child and authenticated user')."""


def _allergy_canonical(entry):
    return {
        "type": entry.get("type"),
        "allergen": entry.get("allergen"),
        "reaction": entry.get("reaction"),
        "severity": entry.get("severity"),
        "confirmed_by_professional": entry.get("confirmed_by_professional"),
    }


def _condition_canonical(entry):
    return {
        "condition_name": entry.get("condition_name"),
        "diagnosed_year": entry.get("diagnosed_year"),
        "status": entry.get("status"),
        "note": entry.get("note"),
    }


def _medication_canonical(entry):
    return {
        "medication_name": entry.get("medication_name"),
        "dose": entry.get("dose"),
        "times_of_day": list(entry.get("times_of_day") or []),
    }


def canonicalize_emergency_card_report(summary):
    """
    Bentuk KANONIK (dict JSON-safe, allowlist field EKSPLISIT) dari
    ringkasan `utils/emergency_card_report.py:build_emergency_card_summary`
    -- SATU-SATUNYA helper dipakai baik preview MAUPUN endpoint PDF buat
    menghitung digest (requirement: "one shared backend helper").

    Kebijakan field (didokumentasikan juga di
    backend/docs/MEDICAL_PROFILE.md):

    DIMASUKKAN (SEMUA field yang tampil di preview JSON MAUPUN PDF):
    child_display_name, birth_date, age_now, blood_type, blood_type_label,
    allergies (LENGKAP tiap entri: type/allergen/reaction/severity/
    confirmed_by_professional), conditions (LENGKAP tiap entri:
    condition_name/diagnosed_year/status/note), regular_medications
    (LENGKAP tiap entri: medication_name/dose/times_of_day -- daftar obat
    rutin AKTIF yang DIDERIVASI, requirement eksplisit "include the
    derived regular medication list"), primary_doctor_name,
    primary_clinic_name, primary_clinic_phone, emergency_contact_name,
    emergency_contact_relationship, emergency_contact_phone,
    emergency_instructions, last_reviewed_at, last_reviewed_by_name,
    has_profile, generated_at (timestamp preview YANG SAMA dipakai ulang
    saat rebuild -- lihat docstring modul), disclaimer, privacy_note.

    DIKECUALIKAN: `capabilities` (response-only, tergantung ROLE
    pemanggil saat itu -- BUKAN bagian isi laporan itu sendiri, requirement
    eksplisit "exclude response-only capabilities"; TIDAK PERNAH ikut
    campur di sini SAMA SEKALI karena fungsi ini CUMA membaca field
    allowlist di bawah lewat `.get()`, `summary["capabilities"]` -- yang
    ditambahkan route SETELAH build_emergency_card_summary() selesai --
    otomatis tidak pernah tersentuh) dan `snapshot_token` itu sendiri
    (jelas bukan bagian konten laporan).

    Deterministik: `json.dumps(..., sort_keys=True)` di
    `digest_emergency_card_report` menormalkan URUTAN KEY di SEMUA level
    (termasuk dict alergi/kondisi/obat bersarang) -- urutan insersi dict
    Python di sini SAMA SEKALI TIDAK memengaruhi digest akhir. Urutan
    LIST alergi/kondisi/obat sendiri SUDAH deterministik dari sumbernya
    (lihat utils/emergency_card_report.py:_sorted_allergies/_sorted_conditions,
    dan _regular_medications yang di-ORDER BY medication_name+id ganda,
    BUKAN urutan ORM yang tidak stabil) -- fungsi ini TIDAK mengurutkan
    ulang, cuma memilih field per entri.
    """
    return {
        "schema_version": EMERGENCY_CARD_SNAPSHOT_SCHEMA_VERSION,
        "child_display_name": summary.get("child_display_name"),
        "birth_date": summary.get("birth_date"),
        "age_now": summary.get("age_now"),
        "blood_type": summary.get("blood_type"),
        "blood_type_label": summary.get("blood_type_label"),
        "allergies": [_allergy_canonical(a) for a in summary.get("allergies") or []],
        "conditions": [_condition_canonical(c) for c in summary.get("conditions") or []],
        "regular_medications": [_medication_canonical(m) for m in summary.get("regular_medications") or []],
        "primary_doctor_name": summary.get("primary_doctor_name"),
        "primary_clinic_name": summary.get("primary_clinic_name"),
        "primary_clinic_phone": summary.get("primary_clinic_phone"),
        "emergency_contact_name": summary.get("emergency_contact_name"),
        "emergency_contact_relationship": summary.get("emergency_contact_relationship"),
        "emergency_contact_phone": summary.get("emergency_contact_phone"),
        "emergency_instructions": summary.get("emergency_instructions"),
        "last_reviewed_at": summary.get("last_reviewed_at"),
        "last_reviewed_by_name": summary.get("last_reviewed_by_name"),
        "has_profile": summary.get("has_profile"),
        "generated_at": summary.get("generated_at"),
        "disclaimer": summary.get("disclaimer"),
        "privacy_note": summary.get("privacy_note"),
    }


def digest_emergency_card_report(summary):
    """
    SHA-256 hex digest dari bentuk kanonik `summary` -- `sort_keys=True`
    menjamin urutan key STABIL di semua level nested, `ensure_ascii=False`
    + encode eksplisit `utf-8` (requirement), `separators=(",", ":")`
    menghapus whitespace opsional (representasi paling ringkas & stabil,
    tidak ada 2 cara berbeda buat "byte yang sama secara logis").
    `None`/`[]`/`""`/angka/boolean semuanya dibedakan APA ADANYA oleh
    `json.dumps` bawaan Python (requirement eksplisit) -- fungsi ini
    TIDAK PERNAH menormalkan/mengoersi tipe sebelum di-dump.
    """
    canonical = canonicalize_emergency_card_report(summary)
    encoded = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def generate_snapshot_token(*, child_id, user_id, preview_at, report_digest):
    """
    Token opaque bertanda tangan (`itsdangerous.URLSafeTimedSerializer`,
    SECRET_KEY Flask yang SUDAH ADA -- TIDAK ADA kriptografi custom).
    Claims SENGAJA minimal -- CUMA child_id/user_id/timestamp
    preview/digest/versi skema, TIDAK PERNAH golongan darah/alergi/
    kondisi/kontak/instruksi darurat/nilai medis apa pun (diverifikasi
    langsung lewat test_emergency_card_pdf_snapshot.py::
    test_snapshot_token_claims_never_contain_medical_or_contact_values).
    `preview_at`: STRING ISO 8601 (hasil `.isoformat()` datetime naive
    WIB) -- disimpan sebagai string biar 100% round-trip lewat JSON
    (encoder default itsdangerous), diparse balik via
    `datetime.fromisoformat` di route saat rebuild laporan.
    """
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=SNAPSHOT_TOKEN_SALT)
    claims = {
        "v": EMERGENCY_CARD_SNAPSHOT_SCHEMA_VERSION,
        "child_id": child_id,
        "user_id": user_id,
        "preview_at": preview_at,
        "digest": report_digest,
    }
    return serializer.dumps(claims)


def decode_snapshot_token(token, *, child_id, user_id):
    """
    Balikin dict claims TERVERIFIKASI, ATAU raise salah satu subclass
    `SnapshotTokenError` di atas:

      - `SnapshotTokenInvalidError`: tanda tangan salah/rusak (token
        diotak-atik/dipalsukan), kedaluwarsa (>SNAPSHOT_TOKEN_MAX_AGE_SECONDS),
        payload bukan dict, ATAUPUN versi skema (`v`) TIDAK COCOK
        `EMERGENCY_CARD_SNAPSHOT_SCHEMA_VERSION` server SAAT INI (server
        sudah upgrade format sejak token ini diterbitkan).
      - `SnapshotTokenUnauthorizedError`: token SAH TAPI `child_id`
        ATAUPUN `user_id` di dalam claims BEDA dari yang diminta SEKARANG
        (requirement: "Confirm the token belongs to the same child and
        authenticated user" -- token curian/salah tempel dari
        anak/sesi lain SELALU ditolak walau tanda tangannya valid).

    Pesan error yang ditampilkan ke klien (dipilih oleh CALLER, bukan
    fungsi ini) SENGAJA generik & tidak membedah alasan penolakan
    spesifik -- TIDAK PERNAH membocorkan isi claims/detail tanda tangan.
    """
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=SNAPSHOT_TOKEN_SALT)
    try:
        claims = serializer.loads(token, max_age=SNAPSHOT_TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        raise SnapshotTokenInvalidError("invalid_or_expired")

    if not isinstance(claims, dict) or claims.get("v") != EMERGENCY_CARD_SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotTokenInvalidError("invalid_or_expired")
    if claims.get("child_id") != child_id or claims.get("user_id") != user_id:
        raise SnapshotTokenUnauthorizedError("wrong_child_or_user")
    return claims


def digests_match(a, b):
    """Perbandingan WAKTU-KONSTAN (requirement: 'Compare digests using a timing-safe comparison') -- jangan pernah `a == b` biasa buat nilai turunan kriptografis."""
    return hmac.compare_digest(a or "", b or "")
