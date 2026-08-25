"""
Doctor Consultation Workflow — Phase 1 (lihat backend/docs/DOCTOR_CONSULTATION.md
buat kontrak lengkap & kebijakan privasi/audit). Endpoint di sini
MELENGKAPI alur kunjungan dokter yang sudah ada (routes/health_routes.py
`doctor-visits`) -- BUKAN modul dokter kedua yang terpisah:

  1. Siapkan konsultasi  -> POST .../doctor-consultation/preview
  2. Review laporan       -> respons JSON preview di atas (dirender frontend)
  3. Unduh PDF            -> POST .../doctor-consultation/pdf
  4. (Lakukan konsultasi -- di luar aplikasi)
  5. Catat hasil kunjungan -> form doctor-visit YANG SUDAH ADA
     (POST /children/<id>/doctor-visits, TIDAK ADA form kedua)

POST dipakai buat KEDUA endpoint (bukan GET) SENGAJA -- payload-nya bisa
memuat pilihan section (sampai 16) + teks transien questions/additional_note
yang TIDAK BOLEH nongol di query string / log proxy / riwayat browser.

TIDAK ADA proses background/scheduler di sini -- PDF SELALU dirender
SINKRON, di memori, per-request (lihat utils/consultation_pdf.py),
PERSIS prinsip PythonAnywhere Free yang sudah ditegakkan di seluruh app.
"""
import re
from datetime import datetime

from flask import Blueprint, g, jsonify, request, send_file

from extensions import db
from utils.access import get_accessible_child, resolve_role, WRITE_ROLES
from utils.audit import DOCTOR_CONSULTATION_PDF_EXPORT_ENTITY_TYPE, record_audit_event
from utils.auth import get_current_user_id
from utils.consultation_pdf import render_consultation_pdf
from utils.consultation_report import (
    ConsultationValidationError,
    MAX_CONSULTATION_BODY_BYTES,
    SECTION_MEDICAL_PROFILE,
    SENSITIVE_SECTIONS,
    build_consultation_report,
    resolve_consultation_period,
    validate_note,
    validate_questions,
    validate_sections,
)
from utils.consultation_snapshot import (
    SnapshotTokenInvalidError, SnapshotTokenUnauthorizedError,
    decode_consultation_snapshot_token, digest_consultation_report,
    generate_consultation_snapshot_token,
)
from utils.snapshot_token import digests_match
from utils.timezone_utils import now_wib, today_wib

doctor_consultation_bp = Blueprint("doctor_consultation", __name__)

_FILENAME_SAFE_RE = re.compile(r"[^a-z0-9-]+")

MISSING_SNAPSHOT_TOKEN_MESSAGE = "Token pratinjau tidak ditemukan. Buat pratinjau ulang sebelum mengunduh PDF."
INVALID_SNAPSHOT_TOKEN_MESSAGE = "Token pratinjau tidak valid atau sudah kedaluwarsa. Buat pratinjau ulang sebelum mengunduh PDF."
UNAUTHORIZED_SNAPSHOT_TOKEN_MESSAGE = "Token pratinjau ini tidak berlaku untuk permintaan ini. Buat pratinjau ulang sebelum mengunduh PDF."
STALE_SNAPSHOT_MESSAGE = "Data laporan konsultasi berubah sejak pratinjau dibuat. Buat pratinjau ulang sebelum mengunduh PDF."


def _require_login_and_child(child_id):
    """(child, error_response_atau_None) -- pola SAMA PERSIS routes/reminder_routes.py:_require_login_and_child."""
    user_id = get_current_user_id()
    if not user_id:
        return None, (jsonify({"error": "Belum login"}), 401)
    child = get_accessible_child(child_id, user_id)
    if not child:
        return None, (jsonify({"error": "Anak tidak ditemukan"}), 404)
    return child, None


def _capabilities(role):
    write = role in WRITE_ROLES
    return {
        "can_preview": role is not None,
        "can_export": write,
        "can_add_private_notes": write,
        "can_record_visit": write,
        # Child Medical Profile & Emergency Card Phase 1 -- section
        # `medical_profile` SENGAJA lebih ketat dari section sensitif
        # lain (illness/medication/doctor_visits, yang boleh Viewer
        # baca lewat preview) -- golongan darah/alergi/kontak darurat
        # HANYA Owner/Editor, Viewer ditolak `403` kalau menyertakannya
        # (lihat _parse_request_payload di bawah).
        "can_include_medical_profile": write,
    }


_OVERSIZED_RESPONSE = ({"error": "Ukuran permintaan terlalu besar"}, 413)


def _read_json_body_within_limit():
    """
    Balikin (data, error_response_atau_None) -- baca body request DENGAN
    batas KETAT `MAX_CONSULTATION_BODY_BYTES`, dua lapis (lihat
    backend/docs/DOCTOR_CONSULTATION.md bagian "Request validation &
    size limits" buat penjelasan lengkap kenapa cuma ngecek header
    Content-Length aja NGGAK CUKUP):

      1. Content-Length TERDEKLARASI (kalau ADA) -- ditolak SEDINI
         mungkin, SEBELUM stream disentuh sama sekali (jalur tercepat,
         nol byte terbaca).
      2. Bounded read AKTUAL dari `request.stream` -- baca PALING BANYAK
         `MAX_CONSULTATION_BODY_BYTES + 1` byte (BUKAN nunggu sampai
         limit global `MAX_CONTENT_LENGTH` 6MB aplikasi baru ketauan
         kegedean). Kalau yang KEBACA lebih dari batas, body-nya
         SUNGGUHAN kelewat -- apa pun kata Content-Length, TERMASUK
         kalau headernya nggak ada sama sekali (request chunked/WSGI
         tanpa panjang terdeklarasi) ATAUPUN kalau headernya ada tapi
         lebih kecil dari isi beneran (proxy/klien nggak beres).

    Byte yang berhasil dibaca (kalau LOLOS batas) di-cache MANUAL ke
    `request._cached_data` -- atribut internal Werkzeug (lihat
    werkzeug/wrappers/request.py:Request.get_data(), method resmi buat
    "baca body 1x, dipakai ulang" yang sama persis dipakai internal
    get_data()/get_json() sendiri) -- SEBELUM `request.get_json()`
    dipanggil, biar dia makein bytes yang SAMA (bukan nyoba baca stream
    lagi, yang saat ini udah abis/kepake sebagian -- baca ulang bakal
    dapet kosong, BUKAN body lengkap).

    Bounded-read ini AMAN buat SEMUA kasus `request.stream` yang
    mungkin (diverifikasi langsung, bukan diasumsikan -- lihat
    tests/test_doctor_consultation.py):
      - Content-Length ada & kecil -> stream Werkzeug sendiri sudah
        dibatasi sepanjang itu, `.read(N+1)` balikin body lengkap apa
        adanya, nggak nunggu/hang.
      - Content-Length nggak ada, WSGI server declare
        `wsgi.input_terminated` (server tau cara nge-terminate stream
        sendiri, mis. chunked) -> Werkzeug bungkus stream-nya
        `LimitedStream` sepanjang `MAX_CONTENT_LENGTH` GLOBAL (6MB) --
        `.read(N+1)` kita STOP JAUH SEBELUM itu, nggak pernah nunggu
        sampai 6MB kebaca buat nemuin body-nya kegedean.
      - Content-Length nggak ada, WSGI server TIDAK declare
        `wsgi.input_terminated` -> Werkzeug SENDIRI (lewat
        `werkzeug.wsgi.get_input_stream`) udah balikin stream KOSONG
        demi keamanan (safe_fallback) -- `.read(N+1)` kita balikin
        b"", lolos batas, lanjut ke `get_json()` yang bakal gagal parse
        JSON dari body kosong (400, bukan diam-diam nerima apa pun).

    `MAX_CONTENT_LENGTH` global aplikasi (config.py, 6MB, buat upload
    foto) TETAP jadi jaring pengaman TERLUAR (Werkzeug sendiri yang
    negakin di layer stream, independen dari kode ini) -- batas 20KB
    di sini SELALU lebih ketat & selalu dicek DULUAN, TIDAK PERNAH
    menggantikan jaring pengaman global itu.
    """
    if request.content_length is not None and request.content_length > MAX_CONSULTATION_BODY_BYTES:
        return None, _OVERSIZED_RESPONSE

    raw = request.stream.read(MAX_CONSULTATION_BODY_BYTES + 1)
    if len(raw) > MAX_CONSULTATION_BODY_BYTES:
        return None, _OVERSIZED_RESPONSE

    request._cached_data = raw
    return request.get_json(silent=True), None


def _parse_request_payload(role, capabilities, today):
    """
    Validasi SELURUH body request -- period, sections, questions,
    additional_note -- SEKALI, dipakai SAMA PERSIS oleh endpoint preview
    maupun pdf (1 sumber kebenaran validasi). Balikin
    (period, sections, questions_text, note_text, data,
    error_response_atau_None) -- `data` (dict JSON mentah yang SUDAH
    lolos bounded-read) DIBALIKIN JUGA (bukan cuma field yang sudah
    divalidasi) supaya endpoint PDF bisa membaca `data.get("snapshot_token")`
    dari body yang SAMA PERSIS TANPA membaca ulang `request.stream`
    (stream cuma bisa dibaca SEKALI -- baca ulang lewat
    `_read_json_body_within_limit()` kedua kalinya bakal dapet body
    KOSONG, lihat docstring fungsi itu).

    `today`: SENGAJA parameter (bukan `today_wib()` dipanggil langsung
    di sini) -- endpoint preview SELALU memakai tanggal SEKARANG,
    endpoint PDF memakai tanggal SEKARANG di LANGKAH VALIDASI ini
    (mengecek bentuk/rentang period yang DIKIRIM ULANG masih legal),
    TAPI merekonstruksi ULANG period-nya lagi SETELAH token diverifikasi
    memakai tanggal BEKU dari token (lihat export_consultation_pdf) --
    2 tujuan berbeda, `today` yang mana dipakai di sini murni buat
    validasi bentuk, BUKAN buat isi laporan yang akhirnya di-digest.

    Field top-level di luar 4 yang dikenal (`period`/`sections`/
    `questions`/`additional_note` -- ATAUPUN `snapshot_token` yang CUMA
    dibaca endpoint PDF secara terpisah, lihat di atas) SENGAJA
    diabaikan diam-diam (dibaca lewat `data.get(...)`, TIDAK PERNAH
    divalidasi allowlist-nya) -- KONSISTEN sama konvensi SELURUH
    endpoint lain di app ini (mis. routes/health_routes.py,
    routes/reminder_routes.py: semuanya baca field yang dikenal
    satu-satu lewat `.get()`, TIDAK ADA yang menolak key request tak
    dikenal). Menambahkan kebijakan "tolak field asing" CUMA di endpoint
    ini bakal jadi perilaku validasi yang nggak konsisten/mengejutkan
    dibanding endpoint lain, jadi SENGAJA tidak ditambahkan di sini juga.
    """
    data, err = _read_json_body_within_limit()
    if err:
        payload, status = err
        return None, None, None, None, None, (jsonify(payload), status)
    if not isinstance(data, dict):
        return None, None, None, None, None, (jsonify({"error": "Format data tidak valid"}), 400)

    try:
        period = resolve_consultation_period(data.get("period"), today)
        sections = validate_sections(data.get("sections"))
        questions_text = validate_questions(data.get("questions"))
        note_text = validate_note(data.get("additional_note"))
    except ConsultationValidationError as exc:
        return None, None, None, None, None, (jsonify({"error": exc.message}), 400)

    wants_private_text = bool(questions_text) or bool(note_text)
    if wants_private_text and not capabilities["can_add_private_notes"]:
        return None, None, None, None, None, (
            jsonify({"error": "Peran Anda tidak bisa menambahkan pertanyaan/catatan tambahan."}), 403
        )

    if SECTION_MEDICAL_PROFILE in sections and not capabilities["can_include_medical_profile"]:
        return None, None, None, None, None, (
            jsonify({"error": "Peran Anda tidak bisa menyertakan bagian Profil Medis & Kartu Darurat."}), 403
        )

    return period, sections, questions_text, note_text, data, None


def _safe_filename_component(text):
    lowered = (text or "").strip().lower().replace(" ", "-")
    cleaned = _FILENAME_SAFE_RE.sub("", lowered)
    return cleaned or "anak"


@doctor_consultation_bp.route("/children/<int:child_id>/doctor-consultation/preview", methods=["POST"])
def preview_consultation(child_id):
    """
    Lihat backend/docs/DOCTOR_CONSULTATION.md bagian "Konsistensi
    snapshot preview -> PDF (token bertanda tangan)" + docstring
    utils/consultation_snapshot.py. `now_wib()` di-sample TEPAT SEKALI
    di sini (bug review Agustus 2026 -- "midnight race": versi
    SEBELUMNYA memanggil `today_wib()` DULUAN buat validasi period,
    BARU `now_wib()` BELAKANGAN buat isi laporan -- 2 pemanggilan jam
    sistem terpisah berarti kalau eksekusi kebetulan melewati tengah
    malam WIB PERSIS di antara keduanya, `period` bisa ke-resolve pakai
    tanggal LAMA sementara `generated_at`/`preview_at` token pakai
    tanggal BARU, bikin PDF yang BENERAN belum berubah ditolak `409`
    palsu -- lihat test_doctor_consultation.py bagian "midnight race").
    `now` (SATU objek, immutable) dipakai buat SEMUANYA: `now.date()`
    buat resolusi period (`_parse_request_payload`), isi laporan (usia,
    "generated_at", resolusi period preset, dll), DAN ditandatangani di
    dalam `snapshot_token` (field `preview_at`) -- biar endpoint PDF
    bisa membangun ulang laporan yang SAMA PERSIS tanpa perlu menyimpan
    apa pun di server. Endpoint ini TIDAK PERNAH lagi memanggil
    `today_wib()`.
    """
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()
    role = resolve_role(child, user_id)
    capabilities = _capabilities(role)

    now = now_wib()
    period, sections, questions_text, note_text, _data, err = _parse_request_payload(role, capabilities, now.date())
    if err:
        return err

    report = build_consultation_report(child, period, sections, questions_text, note_text, period["end_date"], now)

    digest = digest_consultation_report(report)
    snapshot_token = generate_consultation_snapshot_token(
        child_id=child_id, user_id=user_id, preview_at=now.isoformat(), report_digest=digest,
    )

    report["capabilities"] = capabilities
    report["request_id"] = getattr(g, "request_id", None) or "unknown"
    # `sensitive_sections_available` -- allowlist TETAP (bukan cuma yang
    # dipilih user kali ini) biar frontend bisa nunjukin indikator
    # "section ini sensitif" buat SEMUA opsi checkbox, bukan cuma yang
    # kebetulan lagi dicentang.
    report["sensitive_section_codes"] = sorted(SENSITIVE_SECTIONS)
    report["snapshot_token"] = snapshot_token
    return jsonify(report)


@doctor_consultation_bp.route("/children/<int:child_id>/doctor-consultation/pdf", methods=["POST"])
def export_consultation_pdf(child_id):
    """
    Urutan pengecekan SENGAJA (lihat backend/docs/DOCTOR_CONSULTATION.md):
    (1) login+akses anak, (2) otorisasi export Owner/Editor, (3) bounded
    body read, (4) body harus objek JSON, (5) validasi payload &
    section sensitif yang SUDAH ADA (period/sections/questions/note --
    pakai `today_wib()` REAL, MURNI buat validasi bentuk/rentang), (6)
    tanda tangan+kedaluwarsa+versi skema token, (7) token harus milik
    anak+user yang SAMA, (8) parse `preview_at` dari token secara
    defensif, (9) BANGUN ULANG laporan pakai payload yang DIKIRIM ULANG
    + database TERKINI, TAPI period-nya di-RESOLVE ULANG memakai
    `preview_at` BEKU (bukan `today_wib()` lagi) supaya preset periode
    (mis. "7d") tetap merujuk rentang tanggal yang SAMA PERSIS kayak
    saat preview, (10) hash pakai helper kanonik yang SAMA PERSIS
    dipakai preview, (11) bandingkan digest TIMING-SAFE, (12) render
    PDF CUMA kalau cocok, (13) audit CUMA ditulis SETELAH semua validasi
    & pengecekan digest lolos. TIDAK PERNAH merender PDF ATAUPUN
    menulis baris audit buat request yang ditolak di langkah manapun.
    """
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()
    role = resolve_role(child, user_id)
    capabilities = _capabilities(role)

    # Otorisasi DULUAN, SEBELUM body (apalagi ukurannya/token-nya)
    # disentuh sama sekali -- Viewer yang ngirim body raksasa/token
    # apa pun dapet 403 yang SAMA PERSIS kayak Viewer yang ngirim body
    # kecil/valid, TIDAK PERNAH kebedain (413/400 vs 403) berdasarkan
    # ukuran body ATAUPUN validitas token-nya -- konsisten sama pola
    # SELURUH endpoint lain di app ini.
    if not capabilities["can_export"]:
        return jsonify({"error": "Peran Anda tidak bisa mengunduh PDF konsultasi."}), 403

    today = today_wib()
    period, sections, questions_text, note_text, data, err = _parse_request_payload(role, capabilities, today)
    if err:
        return err

    snapshot_token = data.get("snapshot_token")
    if not snapshot_token or not isinstance(snapshot_token, str):
        return jsonify({"error": MISSING_SNAPSHOT_TOKEN_MESSAGE}), 400

    try:
        claims = decode_consultation_snapshot_token(snapshot_token, child_id=child_id, user_id=user_id)
    except SnapshotTokenUnauthorizedError:
        return jsonify({"error": UNAUTHORIZED_SNAPSHOT_TOKEN_MESSAGE}), 403
    except SnapshotTokenInvalidError:
        return jsonify({"error": INVALID_SNAPSHOT_TOKEN_MESSAGE}), 400

    try:
        preview_at = datetime.fromisoformat(claims["preview_at"])
    except (KeyError, TypeError, ValueError):
        # Praktis MUSTAHIL kejadian (claims sudah lolos verifikasi tanda
        # tangan itsdangerous, jadi isinya persis apa yang server SENDIRI
        # tandatangani) -- tetap ditangani secara defensif.
        return jsonify({"error": INVALID_SNAPSHOT_TOKEN_MESSAGE}), 400

    # Re-resolve period pakai TANGGAL BEKU dari token (BUKAN `today` di
    # atas, yang cuma buat validasi bentuk) -- requirement: "use the
    # frozen preview timestamp for... period resolution". Custom range
    # balikin start/end yang SAMA persis apa pun "today"-nya (sudah
    # divalidasi legal di langkah 5); preset (mis. "7d") balikin
    # start/end yang SAMA PERSIS kayak saat preview HANYA kalau di-
    # resolve pakai tanggal preview yang BEKU ini.
    try:
        frozen_period = resolve_consultation_period(data.get("period"), preview_at.date())
    except ConsultationValidationError:
        return jsonify({"error": INVALID_SNAPSHOT_TOKEN_MESSAGE}), 400

    report = build_consultation_report(
        child, frozen_period, sections, questions_text, note_text, frozen_period["end_date"], preview_at,
    )
    current_digest = digest_consultation_report(report)
    if not digests_match(current_digest, claims.get("digest")):
        return jsonify({"error": STALE_SNAPSHOT_MESSAGE}), 409

    buffer = render_consultation_pdf(report)

    # `export_now` (waktu EKSPOR sebenarnya, BUKAN `preview_at` yang
    # dibekukan) dipakai CUMA buat metadata audit + nama file -- dua hal
    # ini TIDAK memengaruhi kesetaraan isi laporan (bukan bagian dari
    # digest), jadi tetap aman mencerminkan waktu unduh yang SEBENARNYA
    # walau lebih belakangan dari waktu preview.
    export_now = now_wib()

    # Audit CUMA buat PDF export (bukan preview -- preview itu baca doang,
    # dipanggil berkali-kali tiap section di-toggle, bakal jadi noise
    # kalau diaudit; lihat backend/docs/DOCTOR_CONSULTATION.md "Audit").
    # `entity_id=0`: TIDAK ADA baris database yang jadi acuan (PDF ini
    # SENGAJA nggak pernah disimpan permanen di server) -- 0 dipakai
    # sebagai sentinel "nggak ada record asli", bukan FK sungguhan
    # (kolom `entity_id` di CaregiverAuditEvent memang bukan FK, lihat
    # models.py). `changed_fields` SENGAJA nggak dipakai (kebijakan
    # utils/audit.py: field itu cuma buat action='update') -- rincian apa
    # yang dipilih/tanggal persis TIDAK disimpan di baris audit ini,
    # keputusan yang didokumentasikan di DOCTOR_CONSULTATION.md.
    record_audit_event(
        child_id=child_id, actor_user_id=user_id, action="create",
        entity_type=DOCTOR_CONSULTATION_PDF_EXPORT_ENTITY_TYPE, entity_id=0,
        recorded_at=export_now,
    )
    db.session.commit()

    filename = f"konsultasi-{_safe_filename_component(child.nickname or child.name)}-{frozen_period['end_date'].isoformat()}.pdf"
    response = send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)
    return response
