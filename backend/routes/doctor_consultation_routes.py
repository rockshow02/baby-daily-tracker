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

from flask import Blueprint, g, jsonify, request, send_file

from extensions import db
from utils.access import get_accessible_child, resolve_role, WRITE_ROLES
from utils.audit import DOCTOR_CONSULTATION_PDF_EXPORT_ENTITY_TYPE, record_audit_event
from utils.auth import get_current_user_id
from utils.consultation_pdf import render_consultation_pdf
from utils.consultation_report import (
    ConsultationValidationError,
    MAX_CONSULTATION_BODY_BYTES,
    SENSITIVE_SECTIONS,
    build_consultation_report,
    resolve_consultation_period,
    validate_note,
    validate_questions,
    validate_sections,
)
from utils.timezone_utils import now_wib, today_wib

doctor_consultation_bp = Blueprint("doctor_consultation", __name__)

_FILENAME_SAFE_RE = re.compile(r"[^a-z0-9-]+")


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


def _parse_request_payload(role, capabilities):
    """
    Validasi SELURUH body request -- period, sections, questions,
    additional_note -- SEKALI, dipakai SAMA PERSIS oleh endpoint preview
    maupun pdf (1 sumber kebenaran validasi). Balikin
    (period, sections, questions_text, note_text, error_response_atau_None).

    Field top-level di luar 4 yang dikenal (`period`/`sections`/
    `questions`/`additional_note`) SENGAJA diabaikan diam-diam (dibaca
    lewat `data.get(...)`, TIDAK PERNAH divalidasi allowlist-nya) --
    KONSISTEN sama konvensi SELURUH endpoint lain di app ini (mis.
    routes/health_routes.py, routes/reminder_routes.py: semuanya baca
    field yang dikenal satu-satu lewat `.get()`, TIDAK ADA yang menolak
    key request tak dikenal). Menambahkan kebijakan "tolak field asing"
    CUMA di endpoint ini bakal jadi perilaku validasi yang nggak
    konsisten/mengejutkan dibanding endpoint lain, jadi SENGAJA tidak
    ditambahkan di sini juga.
    """
    data, err = _read_json_body_within_limit()
    if err:
        payload, status = err
        return None, None, None, None, (jsonify(payload), status)
    if not isinstance(data, dict):
        return None, None, None, None, (jsonify({"error": "Format data tidak valid"}), 400)

    try:
        today = today_wib()
        period = resolve_consultation_period(data.get("period"), today)
        sections = validate_sections(data.get("sections"))
        questions_text = validate_questions(data.get("questions"))
        note_text = validate_note(data.get("additional_note"))
    except ConsultationValidationError as exc:
        return None, None, None, None, (jsonify({"error": exc.message}), 400)

    wants_private_text = bool(questions_text) or bool(note_text)
    if wants_private_text and not capabilities["can_add_private_notes"]:
        return None, None, None, None, (
            jsonify({"error": "Peran Anda tidak bisa menambahkan pertanyaan/catatan tambahan."}), 403
        )

    return period, sections, questions_text, note_text, None


def _safe_filename_component(text):
    lowered = (text or "").strip().lower().replace(" ", "-")
    cleaned = _FILENAME_SAFE_RE.sub("", lowered)
    return cleaned or "anak"


@doctor_consultation_bp.route("/children/<int:child_id>/doctor-consultation/preview", methods=["POST"])
def preview_consultation(child_id):
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()
    role = resolve_role(child, user_id)
    capabilities = _capabilities(role)

    period, sections, questions_text, note_text, err = _parse_request_payload(role, capabilities)
    if err:
        return err

    now = now_wib()
    report = build_consultation_report(child, period, sections, questions_text, note_text, period["end_date"], now)
    report["capabilities"] = capabilities
    report["request_id"] = getattr(g, "request_id", None) or "unknown"
    # `sensitive_sections_available` -- allowlist TETAP (bukan cuma yang
    # dipilih user kali ini) biar frontend bisa nunjukin indikator
    # "section ini sensitif" buat SEMUA opsi checkbox, bukan cuma yang
    # kebetulan lagi dicentang.
    report["sensitive_section_codes"] = sorted(SENSITIVE_SECTIONS)
    return jsonify(report)


@doctor_consultation_bp.route("/children/<int:child_id>/doctor-consultation/pdf", methods=["POST"])
def export_consultation_pdf(child_id):
    child, err = _require_login_and_child(child_id)
    if err:
        return err
    user_id = get_current_user_id()
    role = resolve_role(child, user_id)
    capabilities = _capabilities(role)

    # Otorisasi DULUAN, SEBELUM body (apalagi ukurannya) disentuh sama
    # sekali -- Viewer yang ngirim body raksasa dapet 403 yang SAMA
    # PERSIS kayak Viewer yang ngirim body kecil/valid, TIDAK PERNAH
    # kebedain (413 vs 403) berdasarkan ukuran body-nya -- konsisten
    # sama pola SELURUH endpoint lain di app ini (cek peran/akses
    # SEBELUM validasi payload apa pun, lihat health_routes.py dkk),
    # dan sekalian jadi jalur penolakan TERCEPAT (nol byte stream
    # kebaca) buat request yang emang bakal ditolak apa pun isinya.
    if not capabilities["can_export"]:
        return jsonify({"error": "Peran Anda tidak bisa mengunduh PDF konsultasi."}), 403

    period, sections, questions_text, note_text, err = _parse_request_payload(role, capabilities)
    if err:
        return err

    now = now_wib()
    report = build_consultation_report(child, period, sections, questions_text, note_text, period["end_date"], now)
    buffer = render_consultation_pdf(report)

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
        recorded_at=now,
    )
    db.session.commit()

    filename = f"konsultasi-{_safe_filename_component(child.nickname or child.name)}-{period['end_date'].isoformat()}.pdf"
    response = send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)
    return response
