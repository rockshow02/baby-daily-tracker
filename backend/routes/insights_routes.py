"""
Smart Insights & Weekly Summary — Phase 1. BACA SAJA: endpoint di sini
TIDAK PERNAH menulis/mengubah data anak, jadi TIDAK butuh audit event
(Caregiver Audit Trail cuma mencatat create/update/delete record —
lihat backend/docs/AUDIT_TRAIL.md) dan TIDAK butuh idempotency key
(itu cuma buat POST yang bisa diantrikan offline — lihat
utils/idempotency.py). Semua role (owner/editor/viewer) yang PUNYA
akses baca ke anak ini boleh lihat insight — TIDAK ADA yang disembunyikan
dari viewer di Phase 1 (lihat backend/docs/ROLES_PERMISSIONS.md).

Lihat backend/docs/INSIGHTS.md buat kontrak lengkap response-nya.
"""
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from utils.access import get_accessible_child
from utils.auth import get_current_user_id
from utils.insights_engine import DEFAULT_PERIOD_KEY, SUPPORTED_PERIODS, build_insight_response
from utils.timezone_utils import today_wib

insights_bp = Blueprint("insights", __name__)


@insights_bp.route("/children/<int:child_id>/insights", methods=["GET"])
def get_insights(child_id):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401

    # `get_accessible_child` (BUKAN require_owner_access/require_write_access)
    # — owner/editor/viewer SEMUA lolos di sini, konsisten sama endpoint
    # baca-saja lain (stats, export-json, dst). User yang SAMA SEKALI
    # nggak punya akses dapet 404 yang SAMA PERSIS kayak anak yang nggak
    # ada — nggak pernah bisa mbedain "anak ini ada tapi kamu nggak boleh
    # lihat" dari "anak ini nggak ada" (requirement: outsider nggak boleh
    # tau insight-nya ada atau nggak).
    child = get_accessible_child(child_id, user_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    period_key = request.args.get("period") or DEFAULT_PERIOD_KEY
    if period_key not in SUPPORTED_PERIODS:
        return jsonify({"error": "Periode tidak didukung. Gunakan '7d' atau '30d'."}), 400

    # `today_wib()` DIPANGGIL SEKALI DI SINI (bukan di dalam
    # utils/insights_engine.py) — biar seluruh mesin perhitungan di sana
    # murni/gampang dites pakai tanggal palsu lewat monkeypatch fungsi
    # ini (`insights_routes.today_wib`), TANPA perlu memanipulasi jam
    # sistem beneran. Lihat backend/tests/test_insights.py.
    today = today_wib()
    response = build_insight_response(child_id, period_key, today)
    response["child_id"] = child_id
    response["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    response["request_id"] = getattr(g, "request_id", None) or "unknown"

    return jsonify(response)
