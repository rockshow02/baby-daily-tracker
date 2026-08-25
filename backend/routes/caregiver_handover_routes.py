"""
Caregiver Handover Summary — Phase 1 (lihat
backend/docs/CAREGIVER_HANDOVER.md buat kontrak lengkapnya). Bantu 1
caregiver menyerahkan konteks operasional 24 jam terakhir ke caregiver
lain TANPA harus mereka bongkar satu-satu semua log -- RINGKASAN
OPERASIONAL, BUKAN laporan tren statistik (beda Smart Insights) ATAUPUN
laporan konsultasi dokter (beda Doctor Consultation), BUKAN diagnosis/
saran medis/rekomendasi darurat.

TIDAK ADA proses background/scheduler di sini -- ringkasan SELALU
dihitung SINKRON per-request dari tabel sumber yang sudah ada (lihat
utils/caregiver_handover_summary.py), PERSIS prinsip PythonAnywhere
Free yang sudah ditegakkan di seluruh app ini.
"""
from datetime import timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import insert, literal, select
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import CaregiverHandover, CaregiverHandoverAcknowledgement
from utils.access import (
    ROLE_EDITOR, ROLE_OWNER, WRITE_ROLES, get_accessible_child, resolve_role,
)
from utils.audit import (
    CAREGIVER_HANDOVER_ACKNOWLEDGED_ENTITY_TYPE, CAREGIVER_HANDOVER_CLOSED_ENTITY_TYPE,
    diff_snapshots, record_audit_event, snapshot_fields,
)
from utils.auth import get_current_user_id
from utils.caregiver_handover_engine import HandoverValidationError, validate_note
from utils.caregiver_handover_summary import build_caregiver_handover_summary
from utils.timezone_utils import now_wib

caregiver_handover_bp = Blueprint("caregiver_handover", __name__)

NO_ACCESS_MESSAGE = "Anda tidak punya izin untuk mengakses serah terima ini."
CLOSED_MESSAGE = "Serah terima ini sudah ditutup."

# Batas ukuran body KHUSUS endpoint create/update (cuma berisi `note`,
# dibatasi NOTE_MAX_LEN=1000 karakter -- lihat utils/caregiver_handover_engine.py)
# -- jauh lebih ketat dari MAX_CONTENT_LENGTH global aplikasi (6MB).
MAX_HANDOVER_BODY_BYTES = 4_000
# Batas endpoint acknowledge/close -- body SEHARUSNYA kosong ATAU objek
# kecil (requirement: "Body should be empty or a small JSON object"),
# TIDAK PERNAH butuh field apa pun.
MAX_SMALL_BODY_BYTES = 200
_OVERSIZED_RESPONSE = ({"error": "Ukuran permintaan terlalu besar"}, 413)


def _read_json_body_within_limit(max_bytes=MAX_HANDOVER_BODY_BYTES):
    """
    Bounded-read SAMA PERSIS pola `_read_json_body_within_limit` di
    routes/doctor_consultation_routes.py / routes/medical_profile_routes.py
    -- lihat docstring di sana buat penjelasan lengkap kenapa cuma
    ngecek header Content-Length aja NGGAK CUKUP.

    Balikin `(data, error_response_atau_None, raw_bytes)` -- `raw_bytes`
    dipakai pemanggil yang body-nya OPSIONAL (create/acknowledge) buat
    membedakan "body beneran kosong" (`data is None` KARENA memang tidak
    ada apa-apa dikirim -- SAH, diperlakukan sebagai `{}`) dari "body
    JSON YANG RUSAK" (`data is None` KARENA `get_json(silent=True)` gagal
    parse byte yang BUKAN kosong) -- keduanya sama-sama `data is None`
    dari `get_json(silent=True)`, TIDAK BISA dibedakan tanpa raw bytes.
    """
    if request.content_length is not None and request.content_length > max_bytes:
        return None, _OVERSIZED_RESPONSE, b""
    raw = request.stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        return None, _OVERSIZED_RESPONSE, b""
    request._cached_data = raw
    return request.get_json(silent=True), None, raw


def _can_edit_or_close(role, handover, user_id):
    """
    True kalau `role` (dengan `user_id`) boleh mengubah/menutup
    `handover` ini -- CUMA soal ROLE/KEPEMILIKAN, TIDAK PEDULI status
    open/closed-nya (status dicek TERPISAH di route, biar pesan error-
    nya bisa beda: 403 "tidak punya izin" vs 400 "sudah ditutup",
    requirement: "editing a closed handover is rejected" sebagai kasus
    TERSENDIRI dari otorisasi).

      - owner: SELALU boleh, terlepas siapa pembuatnya.
      - editor: CUMA boleh kalau DIA SENDIRI pembuatnya (requirement:
        "cannot edit/close another Editor's handover unless existing
        product rules explicitly permit it" -- TIDAK ADA aturan begitu
        di app ini, jadi default DITOLAK).
      - viewer (atau role apa pun di luar owner/editor): SELALU False.
    """
    if handover is None:
        return False
    if role == ROLE_OWNER:
        return True
    if role == ROLE_EDITOR:
        return handover.created_by_user_id == user_id
    return False


def _capabilities(role, handover, user_id):
    """
    Kapabilitas DIHITUNG BACKEND, SELALU -- frontend TIDAK PERNAH
    dipercaya soal peran sendiri (requirement eksplisit "do not trust
    frontend role flags"). `can_edit`/`can_close` mensyaratkan handover
    ADA dan MASIH `open` DAN role/kepemilikannya cocok -- SEMUA
    dievaluasi ULANG tiap request (requirement: "re-check access and
    current role on every request").
    """
    can_edit_or_close_now = (
        handover is not None and handover.status == "open" and _can_edit_or_close(role, handover, user_id)
    )
    return {
        "can_view": role is not None,
        "can_create": role in WRITE_ROLES,
        "can_edit": can_edit_or_close_now,
        "can_close": can_edit_or_close_now,
        # SEMUA peran (termasuk Viewer) boleh acknowledge, tetapi CUMA
        # selama handover masih open. Endpoint menegakkan kondisi yang
        # sama secara atomik agar UI basi tidak bisa membuat ack baru
        # setelah request close menang race.
        "can_acknowledge": handover is not None and handover.status == "open" and role is not None,
    }


def _require_login_and_child(child_id):
    user_id = get_current_user_id()
    if not user_id:
        return None, None, (jsonify({"error": "Belum login"}), 401)
    child = get_accessible_child(child_id, user_id)
    if not child:
        return None, None, (jsonify({"error": "Anak tidak ditemukan"}), 404)
    return child, user_id, None


def _require_handover_and_role(handover_id, user_id):
    """
    (handover, child, role, error_response_atau_None). Anak diresolusi
    DARI handover (`handover.child_id`), BUKAN dari URL -- endpoint
    yang dikunci `handover_id` (update/acknowledge/close) TIDAK
    menyertakan `child_id` di path sama sekali (lihat kontrak API).
    User yang TIDAK PUNYA akses ke anak pemilik handover ini dapat
    `404` yang SAMA PERSIS kayak handover yang beneran nggak ada --
    keberadaan handover anak lain TIDAK PERNAH bisa disimpulkan dari
    luar (requirement: "unrelated user: 404").
    """
    handover = db.session.get(CaregiverHandover, handover_id)
    if not handover:
        return None, None, None, (jsonify({"error": "Serah terima tidak ditemukan"}), 404)
    child = get_accessible_child(handover.child_id, user_id)
    if not child:
        return None, None, None, (jsonify({"error": "Serah terima tidak ditemukan"}), 404)
    role = resolve_role(child, user_id)
    return handover, child, role, None


def _acknowledgement_list(handover):
    return [
        a.to_dict()
        for a in handover.acknowledgements.order_by(CaregiverHandoverAcknowledgement.acknowledged_at.asc())
    ]


@caregiver_handover_bp.route("/children/<int:child_id>/caregiver-handover", methods=["GET"])
def get_caregiver_handover(child_id):
    child, user_id, err = _require_login_and_child(child_id)
    if err:
        return err
    role = resolve_role(child, user_id)

    handover = CaregiverHandover.query.filter_by(child_id=child_id, status="open").first()
    capabilities = _capabilities(role, handover, user_id)

    if not handover:
        return jsonify({"handover": None, "summary": None, "acknowledgements": [], "capabilities": capabilities})

    now = now_wib()
    summary = build_caregiver_handover_summary(child, handover, now)
    return jsonify({
        "handover": handover.to_dict(),
        "summary": summary,
        "acknowledgements": _acknowledgement_list(handover),
        "capabilities": capabilities,
    })


@caregiver_handover_bp.route("/children/<int:child_id>/caregiver-handover", methods=["POST"])
def create_caregiver_handover(child_id):
    """
    Jendela 24 jam DIBEKUKAN DI SINI -- SATU sampel `now_wib()`
    (requirement eksplisit), disimpan APA ADANYA ke
    `window_start`/`as_of_at` dan TIDAK PERNAH bergeser lagi
    (utils/caregiver_handover_summary.py SELALU baca dari kolom ini,
    TIDAK PERNAH memanggil jam sistem sendiri).

    Race 2 request BERSAMAAN buat anak yang SAMA ditangani lewat
    partial unique index DB (models.py:CaregiverHandover) -- kalau
    `db.session.flush()` di bawah nabrak constraint itu, `IntegrityError`
    ditangkap eksplisit jadi `409` yang aman, TIDAK PERNAH 500 mentah
    (requirement: "handle the database uniqueness race deterministically").
    """
    child, user_id, err = _require_login_and_child(child_id)
    if err:
        return err
    role = resolve_role(child, user_id)
    if role not in WRITE_ROLES:
        return jsonify({"error": "Peran Anda tidak bisa membuat serah terima."}), 403

    data, size_err, raw = _read_json_body_within_limit()
    if size_err:
        payload, status = size_err
        return jsonify(payload), status
    if data is None and raw.strip():
        return jsonify({"error": "Format data tidak valid"}), 400
    if data is not None and not isinstance(data, dict):
        return jsonify({"error": "Format data tidak valid"}), 400

    try:
        note = validate_note((data or {}).get("note"))
    except HandoverValidationError as exc:
        return jsonify({"error": exc.message}), 400

    now = now_wib()
    handover = CaregiverHandover(
        child_id=child_id, created_by_user_id=user_id,
        window_start=now - timedelta(hours=24), as_of_at=now,
        note=note, status="open", created_at=now, updated_at=now,
    )
    db.session.add(handover)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "Sudah ada serah terima yang masih terbuka untuk anak ini."}), 409

    record_audit_event(
        child_id=child_id, actor_user_id=user_id, action="create",
        entity_type="caregiver_handover", entity_id=handover.id, recorded_at=now,
    )
    db.session.commit()

    capabilities = _capabilities(role, handover, user_id)
    summary = build_caregiver_handover_summary(child, handover, now)
    return jsonify({
        "handover": handover.to_dict(), "summary": summary, "acknowledgements": [], "capabilities": capabilities,
    }), 201


@caregiver_handover_bp.route("/caregiver-handovers/<int:handover_id>", methods=["PUT"])
def update_caregiver_handover(handover_id):
    """
    Update ATOMIK berbasis DATABASE (`UPDATE ... WHERE id=? AND
    status='open'`, `synchronize_session=False`) -- BUKAN cuma cek
    `handover.status` di memori dulu baru UPDATE terpisah, yang rentan
    race (handover sempat ditutup request LAIN di antara cek & tulis).
    `updated_rows == 0` berarti SUDAH ditutup TEPAT SAAT update ini
    berjalan -- balas `400` yang SAMA PERSIS deterministik, TIDAK ADA
    mutasi PARSIAL yang kesimpen (requirement: "editing a closed
    handover is rejected").
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401
    handover, child, role, err = _require_handover_and_role(handover_id, user_id)
    if err:
        return err

    if not _can_edit_or_close(role, handover, user_id):
        return jsonify({"error": NO_ACCESS_MESSAGE}), 403

    data, size_err, _raw = _read_json_body_within_limit()
    if size_err:
        payload, status = size_err
        return jsonify(payload), status
    if not isinstance(data, dict):
        return jsonify({"error": "Format data tidak valid"}), 400

    try:
        note = validate_note(data.get("note"))
    except HandoverValidationError as exc:
        return jsonify({"error": exc.message}), 400

    before = snapshot_fields(handover, "caregiver_handover")
    now = now_wib()
    updated_rows = db.session.query(CaregiverHandover).filter(
        CaregiverHandover.id == handover.id, CaregiverHandover.status == "open",
    ).update({"note": note, "updated_at": now}, synchronize_session=False)

    if updated_rows == 0:
        db.session.rollback()
        return jsonify({"error": CLOSED_MESSAGE}), 400

    # PUT snapshot yang ISINYA SAMA PERSIS (no-op) TIDAK PERNAH
    # menghasilkan baris audit -- diff_snapshots() balikin [] kalau
    # nilai `note`-nya beneran nggak berubah sama sekali.
    changed = diff_snapshots(before, {"note": note}, "caregiver_handover")
    if changed:
        record_audit_event(
            child_id=handover.child_id, actor_user_id=user_id, action="update",
            entity_type="caregiver_handover", entity_id=handover.id, changed_fields=changed, recorded_at=now,
        )
    db.session.commit()
    db.session.refresh(handover)

    capabilities = _capabilities(role, handover, user_id)
    summary = build_caregiver_handover_summary(child, handover, now)
    return jsonify({
        "handover": handover.to_dict(), "summary": summary,
        "acknowledgements": _acknowledgement_list(handover), "capabilities": capabilities,
    })


@caregiver_handover_bp.route("/caregiver-handovers/<int:handover_id>/acknowledge", methods=["POST"])
def acknowledge_caregiver_handover(handover_id):
    """
    Idempoten per (handover_id, user_id) -- ditegakkan `UniqueConstraint`
    DB (models.py:CaregiverHandoverAcknowledgement), BUKAN cuma cek
    query dulu (yang rentan 2 request BERSAMAAN dari user yang SAMA
    lolos cek-nya bareng). Percobaan ULANG (SUDAH pernah acknowledge)
    balikin baris yang SUDAH ADA (200, `created: false`), TIDAK PERNAH
    bikin baris kedua ATAUPUN baris audit kedua.

    Acknowledgement BARU cuma boleh untuk handover `open`. Insert-nya
    memakai SATU statement database `INSERT ... SELECT ... WHERE
    status='open'`, bukan check-then-insert di Python. Karena write
    SQLite diserialisasi, race close-vs-ack punya dua hasil yang sah:
    ack menang (201, lalu close boleh sukses), atau close menang (409,
    tanpa ack/audit baru). Retry ack yang SUDAH berhasil tetap idempoten
    200 walau handover kemudian ditutup.
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401
    handover, child, role, err = _require_handover_and_role(handover_id, user_id)
    if err:
        return err

    data, size_err, raw = _read_json_body_within_limit(MAX_SMALL_BODY_BYTES)
    if size_err:
        payload, status = size_err
        return jsonify(payload), status
    if data is None and raw.strip():
        return jsonify({"error": "Format data tidak valid"}), 400
    if data is not None and not isinstance(data, dict):
        return jsonify({"error": "Format data tidak valid"}), 400

    now = now_wib()
    existing = CaregiverHandoverAcknowledgement.query.filter_by(
        handover_id=handover.id, user_id=user_id,
    ).first()
    if existing:
        return jsonify({"acknowledgement": existing.to_dict(), "created": False})

    # Satu statement atomik: tidak ada celah antara "masih open?" dan
    # INSERT yang dapat dimenangkan request close dari transaksi lain.
    insert_if_open = insert(CaregiverHandoverAcknowledgement).from_select(
        ["handover_id", "user_id", "acknowledged_at"],
        select(literal(handover.id), literal(user_id), literal(now)).where(
            select(CaregiverHandover.id).where(
                CaregiverHandover.id == handover.id,
                CaregiverHandover.status == "open",
            ).exists()
        ),
    )
    try:
        result = db.session.execute(insert_if_open)
    except IntegrityError:
        # Race: request LAIN dari user yang SAMA sudah lebih dulu
        # nyimpen baris acknowledge-nya SESAAT sebelum ini -- ambil
        # balik baris yang beneran tersimpan, BUKAN dianggap gagal.
        db.session.rollback()
        existing = CaregiverHandoverAcknowledgement.query.filter_by(
            handover_id=handover.id, user_id=user_id,
        ).first()
        return jsonify({"acknowledgement": existing.to_dict() if existing else None, "created": False})

    if result.rowcount != 1:
        db.session.rollback()
        return jsonify({"error": CLOSED_MESSAGE}), 409

    ack = CaregiverHandoverAcknowledgement.query.filter_by(
        handover_id=handover.id, user_id=user_id,
    ).one()

    record_audit_event(
        child_id=handover.child_id, actor_user_id=user_id, action="create",
        entity_type=CAREGIVER_HANDOVER_ACKNOWLEDGED_ENTITY_TYPE, entity_id=ack.id, recorded_at=now,
    )
    db.session.commit()
    return jsonify({"acknowledgement": ack.to_dict(), "created": True}), 201


@caregiver_handover_bp.route("/caregiver-handovers/<int:handover_id>/close", methods=["POST"])
def close_caregiver_handover(handover_id):
    """
    Idempoten lewat UPDATE ATOMIK bersyarat (`WHERE status='open'`,
    persis pola `update_caregiver_handover` di atas) -- `updated_rows == 1`
    berarti REQUEST INI yang beneran menutupnya (SATU-SATUNYA yang
    audit), `updated_rows == 0` berarti SUDAH tertutup (oleh request
    lain YANG MENANG race, ATAUPUN memang sudah tertutup dari
    sebelumnya) -- balas `200` yang SAMA (bukan error) DUA-DUANYA,
    TIDAK PERNAH 500 (requirement: "a second close does not cause a
    500", "closing must be idempotent"). Dengan pola ini, BERAPA PUN
    banyaknya request close BERSAMAAN yang tiba, TEPAT SATU baris
    audit yang tercatat -- bukan mengandalkan cek-lalu-tulis di memori
    yang rentan race.
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401
    handover, child, role, err = _require_handover_and_role(handover_id, user_id)
    if err:
        return err

    if not _can_edit_or_close(role, handover, user_id):
        return jsonify({"error": NO_ACCESS_MESSAGE}), 403

    now = now_wib()
    updated_rows = db.session.query(CaregiverHandover).filter(
        CaregiverHandover.id == handover.id, CaregiverHandover.status == "open",
    ).update(
        {"status": "closed", "closed_at": now, "closed_by_user_id": user_id, "updated_at": now},
        synchronize_session=False,
    )

    if updated_rows == 1:
        record_audit_event(
            child_id=handover.child_id, actor_user_id=user_id, action="create",
            entity_type=CAREGIVER_HANDOVER_CLOSED_ENTITY_TYPE, entity_id=handover.id, recorded_at=now,
        )
    db.session.commit()
    db.session.refresh(handover)

    return jsonify({"handover": handover.to_dict()})
