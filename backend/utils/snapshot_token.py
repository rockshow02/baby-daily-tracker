"""
Primitif GENERIK token snapshot bertanda tangan (itsdangerous) -- SATU
implementasi tanda-tangan/verifikasi/expiry/hashing/perbandingan
timing-safe yang dipakai BEBERAPA fitur snapshot preview->PDF di app
ini (Child Medical Profile & Emergency Card, DAN Doctor Consultation)
TANPA menduplikasi logic kriptografi (requirement: "Avoid copying
cryptographic/token-validation logic unnecessarily").

Setiap fitur pemanggil TETAP punya SALT dan VERSI SKEMA TERPISAH
sendiri-sendiri (parameter WAJIB di sini, BUKAN nilai default) --
requirement eksplisit: "keep separate salts and schema versions for
different token purposes". `itsdangerous` menurunkan kunci HMAC yang
BERBEDA per salt (walau `SECRET_KEY` dasarnya sama), jadi token 1 fitur
SECARA KRIPTOGRAFIS TIDAK PERNAH valid dipakai buat fitur lain --
diverifikasi langsung lewat test (Emergency Card token ditolak endpoint
Doctor Consultation, dan sebaliknya).

TANDA TANGAN, BUKAN ENKRIPSI (requirement: dokumentasikan ini
eksplisit): `itsdangerous.URLSafeTimedSerializer` CUMA menjamin claims
TIDAK BISA diubah tanpa ketahuan (tanda tangan HMAC gagal verifikasi
kalau ada byte yang berubah) dan timestamp-nya TIDAK BISA dipalsukan --
isinya SENDIRI cuma di-encode base64url, BUKAN dienkripsi. SIAPA PUN
yang memegang string token bisa MEMBACA payload-nya (base64-decode
biasa, TANPA kunci apa pun, TANPA perlu tahu SECRET_KEY). Keamanan
fitur yang memakai modul ini bergantung SEPENUHNYA pada TIDAK PERNAH
menaruh nilai sensitif (medis/kontak/pertanyaan/catatan/apa pun yang
tidak boleh terbaca pihak yang kebetulan memegang token) di dalam
claims -- BUKAN pada kerahasiaan token itu sendiri. Lihat docstring
`utils/emergency_card_snapshot.py`/`utils/consultation_snapshot.py`
buat daftar field yang secara SADAR dikecualikan dari masing-masing
claims fitur.
"""
import hashlib
import hmac
import json

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


class SnapshotTokenError(ValueError):
    """Basis error token snapshot generik -- TIDAK PERNAH di-raise langsung, lihat 2 subclass di bawah."""


class SnapshotTokenInvalidError(SnapshotTokenError):
    """Token hilang/rusak/tanda tangan salah/kedaluwarsa/versi skema tidak cocok -- caller SEHARUSNYA balas 400 (bukan 409 -- ini BUKAN kasus 'data berubah', tokennya sendiri yang tidak bisa dipercaya lagi)."""


class SnapshotTokenUnauthorizedError(SnapshotTokenError):
    """Token SAH (tanda tangan & masa berlaku valid) TAPI diterbitkan buat anak/pengguna LAIN -- caller SEHARUSNYA balas 403."""


def generate_signed_snapshot_token(*, salt, claims):
    """
    Tandatangani `claims` (dict JSON-safe) pakai SECRET_KEY Flask yang
    SUDAH ADA + `salt` milik fitur pemanggil -- TIDAK ADA kriptografi
    custom (requirement eksplisit). `claims` WAJIB sudah berisi SEMUA
    field identitas (mis. child_id/user_id) yang mau dicocokkan caller
    lewat `decode_signed_snapshot_token` di bawah; modul ini sendiri
    TIDAK PERNAH menambah/mengubah isi `claims`.
    """
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)
    return serializer.dumps(claims)


def decode_signed_snapshot_token(
    token, *, salt, max_age_seconds, expected_schema_version, child_id, user_id,
    schema_key="v", child_id_key="child_id", user_id_key="user_id",
):
    """
    Verifikasi tanda tangan+expiry, lalu cocokkan identitas -- balikin
    dict claims TERVERIFIKASI, ATAU raise:

      - `SnapshotTokenInvalidError`: tanda tangan salah/rusak (token
        diotak-atik/dipalsukan ATAUPUN token fitur LAIN yang salahnya
        ditempel di sini -- salt beda bikin verifikasi tanda tangan
        GAGAL TOTAL, bukan cuma claims-nya beda), kedaluwarsa
        (>`max_age_seconds`), payload bukan dict, ATAUPUN versi skema
        (`claims[schema_key]`) TIDAK COCOK `expected_schema_version`.
      - `SnapshotTokenUnauthorizedError`: token SAH (buat FITUR yang
        SAMA) TAPI `child_id`/`user_id` di dalam claims BEDA dari yang
        diminta SEKARANG -- token curian/salah tempel dari anak/sesi
        lain SELALU ditolak walau tanda tangannya valid.

    Pesan error yang ditampilkan ke klien (dipilih oleh CALLER, bukan
    fungsi ini) SENGAJA generik & tidak membedah alasan penolakan
    spesifik -- TIDAK PERNAH membocorkan isi claims/detail tanda tangan.
    """
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)
    try:
        claims = serializer.loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        raise SnapshotTokenInvalidError("invalid_or_expired")

    if not isinstance(claims, dict) or claims.get(schema_key) != expected_schema_version:
        raise SnapshotTokenInvalidError("invalid_or_expired")
    if claims.get(child_id_key) != child_id or claims.get(user_id_key) != user_id:
        raise SnapshotTokenUnauthorizedError("wrong_child_or_user")
    return claims


def digests_match(a, b):
    """Perbandingan WAKTU-KONSTAN (requirement: 'Compare... using hmac.compare_digest') -- jangan pernah `a == b` biasa buat nilai turunan kriptografis."""
    return hmac.compare_digest(a or "", b or "")


def compute_sha256_digest(canonical_obj):
    """
    SHA-256 hex digest dari `canonical_obj` (dict/list JSON-safe) --
    `sort_keys=True` menjamin urutan KEY stabil di SEMUA level nested
    (dict alergi/kondisi/section konsultasi bersarang termasuk), urutan
    insersi dict Python di kode pemanggil SAMA SEKALI tidak memengaruhi
    digest akhir. `ensure_ascii=False` + encode eksplisit `utf-8`
    (requirement), `separators=(",", ":")` menghapus whitespace opsional
    (representasi paling ringkas & stabil -- tidak ada 2 cara berbeda
    buat "byte yang sama secara logis"). `None`/`[]`/`""`/angka/boolean
    semuanya dibedakan APA ADANYA oleh `json.dumps` bawaan Python
    (requirement eksplisit) -- fungsi ini TIDAK PERNAH menormalkan/
    mengoersi tipe sebelum di-dump.

    `default=str`: jaring pengaman DEFENSIF -- kalau suatu saat nilai
    non-JSON-native (mis. `datetime.date` mentah) lolos masuk ke
    `canonical_obj` (harusnya TIDAK PERNAH terjadi, semua builder laporan
    di app ini SUDAH `.isoformat()` sebelum mengembalikan data), fungsi
    ini TIDAK crash -- distringifikasi APA ADANYA (`str(date(...))` ==
    `date(...).isoformat()`, representasi yang SAMA persis) alih-alih
    melempar `TypeError`. Ini murni jaring pengaman tambahan (Emergency
    Card sudah diverifikasi manual bebas dari kasus ini, TIDAK ADA
    perubahan perilaku buat fitur itu); laporan Doctor Consultation jauh
    lebih besar permukaannya (16 jenis section), jadi lapis pengaman ini
    dipertahankan SENGAJA buat fitur itu.
    """
    encoded = json.dumps(
        canonical_obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
