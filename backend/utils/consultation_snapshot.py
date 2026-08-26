"""
Doctor Consultation Snapshot-Safe PDF Export (bug review Agustus 2026).
Lihat backend/docs/DOCTOR_CONSULTATION.md bagian "Konsistensi snapshot
preview -> PDF (token bertanda tangan)" buat kontrak lengkap, dan
utils/emergency_card_snapshot.py buat fitur SEJENIS yang lebih dulu ada
(struktur modul ini SENGAJA dibuat semirip mungkin -- pola yang SAMA,
data yang beda).

RISIKO yang diperbaiki: `activeSnapshot` di frontend
(components/DoctorConsultationScreen.jsx) sudah mencegah EDIT LOKAL
(form yang diubah user SENDIRI) diam-diam mengubah payload yang
diekspor -- TAPI endpoint PDF backend TETAP membangun ulang laporan
dari state DATABASE TERKINI saat request PDF datang. Kalau caregiver
LAIN mengubah data feeding/tidur/kesehatan/obat/vaksinasi/pertumbuhan/
profil medis/dll -- ATAUPUN section apa pun yang DIPILIH user ini --
di antara waktu preview & unduh PDF, PDF yang dihasilkan BISA BEDA dari
laporan yang sudah caregiver review & setujui privasinya. `editCounterRef`/
`requestSeqRef` frontend CUMA melindungi dari race/edit LEWAT INSTANCE
FRONTEND YANG SAMA, TIDAK PERNAH dari perubahan EKSTERNAL (caregiver
lain, request lain, waktu yang berlalu).

SOLUSI: arsitektur STATELESS yang SAMA PERSIS Emergency Card, primitif
tanda-tangan/hashing GENERIK di-REUSE dari utils/snapshot_token.py
(TIDAK menduplikasi logic kriptografi) -- CUMA salt & versi skema
TERPISAH (requirement eksplisit "keep separate salts and schema
versions for different token purposes"), dan kanonikalisasi/allowlist
sendiri karena BENTUK laporannya beda total (16 jenis section
heterogen vs 1 ringkasan profil medis Emergency Card).

  1. Preview men-sample `now_wib()` SEKALI, membangun laporan penuh
     (utils/consultation_report.py:build_consultation_report), menghitung
     digest dari REPRESENTASI KANONIK-nya (`canonicalize_consultation_report`
     + `digest_consultation_report` di bawah), lalu menandatangani token
     opaque yang CUMA berisi child_id, user_id, timestamp preview,
     digest, dan versi skema -- TIDAK PERNAH pertanyaan/catatan/data
     medis/penyakit/obat/kunjungan dokter/detail menyusui-tidur/detail
     vaksinasi/isi section apa pun. Token dikembalikan BERSAMA hasil
     preview (field `snapshot_token`).
  2. Endpoint PDF WAJIB menerima token itu balik. Token diverifikasi
     (tanda tangan + kedaluwarsa + child/user COCOK), laporan DIBANGUN
     ULANG memakai payload yang DIKIRIM ULANG (period/sections/
     questions/note -- WAJIB, laporan TIDAK BISA dibangun ulang dari
     token doang, token cuma bawa digest+identitas, BUKAN isi laporan)
     DAN timestamp preview YANG SAMA PERSIS dari token (BUKAN
     `now_wib()` baru) -- digest laporan yang baru dibangun ulang
     dibandingkan TIMING-SAFE dengan digest di token; TIDAK COCOK ->
     `409`, TIDAK PERNAH merender PDF yang beda dari yang sudah
     di-preview & dikonfirmasi.

TANDA TANGAN, BUKAN ENKRIPSI: lihat docstring utils/snapshot_token.py
-- klaim token CUMA di-base64url-encode, SIAPA PUN yang memegang string
token bisa membacanya. Keamanannya bergantung SEPENUHNYA pada TIDAK
PERNAH menaruh nilai sensitif di claims (lihat daftar field yang
DIKECUALIKAN di bawah), BUKAN kerahasiaan token.

TIDAK ADA state disimpan di server ANTARA preview & PDF -- token ITU
SENDIRI membawa semua yang dibutuhkan (child_id/user_id/preview_at/
digest), TIDAK ADA Redis/Celery/worker/cron/cache lintas-request/tabel
DB baru -- persis prinsip PythonAnywhere Free yang ditegakkan di
seluruh app ini.
"""
from utils.consultation_report import SECTION_CODES
from utils.snapshot_token import (
    SnapshotTokenError, SnapshotTokenInvalidError, SnapshotTokenUnauthorizedError,
    compute_sha256_digest, decode_signed_snapshot_token, digests_match, generate_signed_snapshot_token,
)

# Salt TERPISAH dari Emergency Card (utils/emergency_card_snapshot.py:
# SNAPSHOT_TOKEN_SALT) DAN dari token login (utils/auth.py) -- 3 jenis
# token ini SENGAJA tidak bisa saling dipakai silang (diverifikasi
# langsung lewat test: token Emergency Card ditolak endpoint konsultasi,
# dan sebaliknya).
CONSULTATION_SNAPSHOT_SALT = "doctor-consultation-snapshot-v1"

# 15 menit -- SAMA persis Emergency Card (requirement: "short expiry,
# preferably 10-15 minutes"), cukup buat caregiver baca laporan &
# memutuskan unduh, cukup pendek biar token lama tidak jadi risiko praktis.
CONSULTATION_SNAPSHOT_MAX_AGE_SECONDS = 15 * 60

# Versi BENTUK KANONIK/token snapshot laporan konsultasi -- independen
# dari versi skema Emergency Card. Menaikkan angka ini bikin SEMUA token
# lama otomatis ditolak (versi tidak cocok) tanpa logic migrasi apa pun.
CONSULTATION_SNAPSHOT_SCHEMA_VERSION = 1


def _canonical_period(period):
    if not period:
        return None
    return {
        "preset": period.get("preset"),
        "start_date": period.get("start_date"),
        "end_date": period.get("end_date"),
        "timezone": period.get("timezone"),
        "days": period.get("days"),
    }


def _canonical_sections(sections):
    """
    Allowlist di level KODE SECTION (16 kode TETAP di SECTION_CODES) --
    isi tiap section diikutkan APA ADANYA (bukan dihitung ulang/
    dinormalisasi di sini), BUKAN dihand-allowlist sampai ke tiap field
    nested-nya. Keputusan SADAR (didokumentasikan di
    backend/docs/DOCTOR_CONSULTATION.md): 16 section bentuknya SANGAT
    heterogen (metrik agregat/daftar entri/status vaksinasi/kartu
    insight/dll) -- meng-hand-allowlist SETIAP field nested-nya akan
    JADI TIDAK SINKRON kalau utils/consultation_report.py menambah
    field baru ke salah satu section builder di masa depan (field baru
    itu diam-diam TIDAK ikut ke digest, memberi RASA AMAN PALSU --
    persis kebalikan dari tujuan fitur ini). Menyertakan APA ADANYA
    (dibatasi ke KODE section yang DIKENAL saja -- key aneh yang
    seharusnya tidak pernah ada otomatis tidak pernah ikut) justru
    LEBIH KONSERVATIF: perubahan field APA PUN di section manapun
    OTOMATIS ikut memengaruhi digest, tanpa perlu modul ini
    dimutakhirkan manual tiap section builder berubah. Ini AMAN karena
    tiap section builder SUDAH menerapkan data-minimization-nya sendiri
    SEBELUM mengembalikan datanya (`notes` bebas-teks/`custom_label`/dll
    TIDAK PERNAH disertakan -- lihat docstring utils/consultation_report.py)
    -- isi section yang sampai ke sini SUDAH berupa permukaan yang
    di-vetting aman utk laporan, bukan baris DB mentah.
    """
    return {code: sections[code] for code in SECTION_CODES if code in (sections or {})}


def canonicalize_consultation_report(report):
    """
    Bentuk KANONIK (dict JSON-safe) dari `report` -- keluaran
    `utils/consultation_report.py:build_consultation_report` -- SATU-
    SATUNYA helper dipakai BAIK preview MAUPUN endpoint PDF buat
    menghitung digest (requirement: "one explicit shared canonicalization
    helper").

    DIMASUKKAN (SEMUA field yang tampil di preview JSON MAUPUN PDF,
    requirement eksplisit "include all visible preview/PDF report
    data"): `child_id`, `child_display_name`, `period` (preset resolusi
    -- termasuk `start_date`/`end_date` -- requirement "include the
    resolved period"), `generated_at` (timestamp preview YANG SAMA
    dipakai ulang saat rebuild), `disclaimer`, `privacy_note`,
    `generated_statement`, `included_sections` (requirement "include...
    the included section list"), `sensitive_sections_included`, dan
    `sections` (SELURUH isi tiap section yang TERPILIH -- termasuk
    field truncation/total_count_in_period per section, requirement
    "include truncation flags and capped-row metadata"; termasuk teks
    `questions`/`note` TRANSIEN kalau section-nya dipilih, requirement
    eksplisit "include transient questions and caregiver notes because
    they appear in the report"; termasuk isi section `medical_profile`
    kalau dipilih, requirement eksplisit "include selected medical-
    profile content" -- lihat `_canonical_sections` di atas).

    DIKECUALIKAN (requirement eksplisit "exclude capabilities, snapshot
    token, HTTP metadata, and request ID unless printed in the PDF"):
    `capabilities`, `request_id`, `sensitive_section_codes` (allowlist
    section sensitif yang TETAP, bukan bagian isi laporan ini) --
    TIDAK PERNAH ikut campur SAMA SEKALI karena fungsi ini CUMA membaca
    field allowlist eksplisit di atas; ketiganya ditambahkan ROUTE
    SETELAH `build_consultation_report()` selesai, jadi otomatis tidak
    pernah tersentuh fungsi ini (persis pola
    utils/emergency_card_snapshot.py).

    Deterministik: `sort_keys=True` (lihat
    utils/snapshot_token.py:compute_sha256_digest) menormalkan urutan
    KEY di semua level nested -- urutan insersi dict Python di sini
    tidak berpengaruh. Urutan LIST (`included_sections`,
    `sensitive_sections_included`, entri tiap section) SUDAH
    deterministik dari sumbernya (lihat `validate_sections` -- urutan
    TETAP ngikutin SECTION_CODES, bukan urutan request; dan
    utils/consultation_report.py/utils/insights_engine.py yang SEMUA
    query list-nya sekarang pakai tie-breaker `id` SEKUNDER -- lihat
    riwayat perubahan modul itu) -- fungsi ini TIDAK mengurutkan ulang
    apa pun, cuma memilih field.
    """
    return {
        "schema_version": CONSULTATION_SNAPSHOT_SCHEMA_VERSION,
        "child_id": report.get("child_id"),
        "child_display_name": report.get("child_display_name"),
        "period": _canonical_period(report.get("period")),
        "generated_at": report.get("generated_at"),
        "disclaimer": report.get("disclaimer"),
        "privacy_note": report.get("privacy_note"),
        "generated_statement": report.get("generated_statement"),
        "included_sections": list(report.get("included_sections") or []),
        "sensitive_sections_included": list(report.get("sensitive_sections_included") or []),
        "sections": _canonical_sections(report.get("sections")),
    }


def digest_consultation_report(report):
    """SHA-256 hex digest dari bentuk kanonik `report` -- lihat `utils/snapshot_token.py:compute_sha256_digest` buat detail encoding (termasuk kenapa `default=str` dipertahankan sebagai jaring pengaman buat laporan sebesar ini)."""
    return compute_sha256_digest(canonicalize_consultation_report(report))


def generate_consultation_snapshot_token(*, child_id, user_id, preview_at, report_digest):
    """
    Token opaque bertanda tangan. Claims SENGAJA minimal -- CUMA
    child_id/user_id/timestamp preview/digest/versi skema. TIDAK PERNAH
    ditaruh di claims (requirement eksplisit, diverifikasi langsung
    lewat test_snapshot_token_claims_contain_only_approved_fields +
    test_no_medical_data_in_decoded_claims_or_serialized_token):
    pertanyaan (`questions`), catatan caregiver (`additional_note`),
    data profil medis, riwayat sakit, obat/dosis, kunjungan dokter,
    detail menyusui/tidur, detail vaksinasi, isi section APA PUN, atau
    nilai kesehatan/kontak lain manapun. `preview_at`: string ISO 8601
    (datetime naive WIB) -- round-trip 100% lewat JSON, diparse balik
    via `datetime.fromisoformat` di route saat rebuild laporan.
    """
    claims = {
        "v": CONSULTATION_SNAPSHOT_SCHEMA_VERSION,
        "child_id": child_id,
        "user_id": user_id,
        "preview_at": preview_at,
        "digest": report_digest,
    }
    return generate_signed_snapshot_token(salt=CONSULTATION_SNAPSHOT_SALT, claims=claims)


def decode_consultation_snapshot_token(token, *, child_id, user_id):
    """Balikin dict claims TERVERIFIKASI, ATAU raise `SnapshotTokenInvalidError` (400) / `SnapshotTokenUnauthorizedError` (403) -- lihat utils/snapshot_token.py buat penjelasan lengkap 2 subclass itu."""
    return decode_signed_snapshot_token(
        token,
        salt=CONSULTATION_SNAPSHOT_SALT,
        max_age_seconds=CONSULTATION_SNAPSHOT_MAX_AGE_SECONDS,
        expected_schema_version=CONSULTATION_SNAPSHOT_SCHEMA_VERSION,
        child_id=child_id,
        user_id=user_id,
    )
