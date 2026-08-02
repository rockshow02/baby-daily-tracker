from datetime import datetime

from flask import Blueprint, request, jsonify, session

from extensions import db
from models import Child, GrowthMeasurement, User
from utils.telegram import notify_other_caregivers
from utils.access import get_accessible_child
from utils.auth import get_current_user_id
from utils.timezone_utils import today_wib
from utils.growth_calc import evaluate_measurement, get_reference, value_at_zscore

growth_bp = Blueprint("growth", __name__)


def _owned_child(child_id):
    user_id = get_current_user_id()
    if not user_id:
        return None
    return get_accessible_child(child_id, user_id)


def _age_months_precise(birth_date, on_date):
    """Usia dalam bulan pecahan (buat interpolasi acuan WHO yang lebih presisi)."""
    days = (on_date - birth_date).days
    return days / 30.4375  # rata-rata jumlah hari per bulan


def _enrich(measurement, child):
    """Tambahkan z-score/persentil/status WHO ke tiap measurement."""
    age_months = _age_months_precise(child.birth_date, measurement.measured_date)
    data = measurement.to_dict()
    data["age_months"] = round(age_months, 1)

    for key, mtype in [
        ("weight_kg", "weight"),
        ("height_cm", "height"),
        ("head_circumference_cm", "head_circumference"),
    ]:
        value = getattr(measurement, key)
        result = evaluate_measurement(mtype, value, child.gender, age_months) if value is not None else None
        data[f"{mtype}_who"] = result

    return data


@growth_bp.route("/children/<int:child_id>/growth-measurements", methods=["GET"])
def list_growth_measurements(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    measurements = (
        GrowthMeasurement.query.filter_by(child_id=child_id)
        .order_by(GrowthMeasurement.measured_date.asc())
        .all()
    )
    return jsonify([_enrich(m, child) for m in measurements])


@growth_bp.route("/children/<int:child_id>/growth-measurements", methods=["POST"])
def create_growth_measurement(child_id):
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    data = request.get_json() or {}
    measured_date_str = data.get("measured_date")
    if not measured_date_str:
        return jsonify({"error": "measured_date wajib diisi"}), 400

    weight_kg = data.get("weight_kg")
    height_cm = data.get("height_cm")
    head_circumference_cm = data.get("head_circumference_cm")

    if weight_kg is None and height_cm is None and head_circumference_cm is None:
        return jsonify({"error": "Isi minimal salah satu: berat, tinggi, atau lingkar kepala"}), 400

    if weight_kg is not None and not (0.5 <= float(weight_kg) <= 40):
        return jsonify({"error": "Berat tidak wajar (0.5-40 kg)"}), 400
    if height_cm is not None and not (20 <= float(height_cm) <= 130):
        return jsonify({"error": "Tinggi tidak wajar (20-130 cm)"}), 400
    if head_circumference_cm is not None and not (20 <= float(head_circumference_cm) <= 60):
        return jsonify({"error": "Lingkar kepala tidak wajar (20-60 cm)"}), 400

    measurement = GrowthMeasurement(
        created_by_user_id=get_current_user_id(),
        child_id=child_id,
        measured_date=datetime.strptime(measured_date_str, "%Y-%m-%d").date(),
        weight_kg=weight_kg,
        height_cm=height_cm,
        head_circumference_cm=head_circumference_cm,
        notes=data.get("notes"),
    )
    db.session.add(measurement)
    db.session.commit()
    notify_other_caregivers(child, get_current_user_id(), f"📈 {User.query.get(get_current_user_id()).name} mencatat data pertumbuhan untuk {child.nickname or child.name}.")
    return jsonify(_enrich(measurement, child)), 201


@growth_bp.route("/growth-reference-curve", methods=["GET"])
def growth_reference_curve():
    """
    Kurva acuan WHO (pita -2SD/median/+2SD) per bulan usia, buat digambar
    sebagai latar belakang chart. Tidak butuh login karena datanya statis.
    Query params: measurement_type, gender, max_months (default 24)
    """
    measurement_type = request.args.get("measurement_type")
    gender = request.args.get("gender")
    max_months = int(request.args.get("max_months", 24))

    if measurement_type not in ("weight", "height", "head_circumference") or gender not in ("L", "P"):
        return jsonify({"error": "measurement_type/gender tidak valid"}), 400

    curve = []
    for month in range(0, max_months + 1):
        ref = get_reference(measurement_type, gender, month)
        if not ref:
            continue
        curve.append({
            "age_months": month,
            "sd_neg2": round(value_at_zscore(ref, -2), 2),
            "median": round(value_at_zscore(ref, 0), 2),
            "sd_pos2": round(value_at_zscore(ref, 2), 2),
        })
    return jsonify(curve)


@growth_bp.route("/growth-measurements/<int:measurement_id>", methods=["PUT", "DELETE"])
def update_or_delete_growth_measurement(measurement_id):
    measurement = GrowthMeasurement.query.get_or_404(measurement_id)
    child = _owned_child(measurement.child_id)
    if not child:
        return jsonify({"error": "Tidak diizinkan"}), 403

    if request.method == "DELETE":
        db.session.delete(measurement)
        db.session.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
    if "measured_date" in data:
        measurement.measured_date = datetime.strptime(data["measured_date"], "%Y-%m-%d").date()
    if "weight_kg" in data:
        if data["weight_kg"] is not None and not (0.5 <= float(data["weight_kg"]) <= 40):
            return jsonify({"error": "Berat tidak wajar (0.5-40 kg)"}), 400
        measurement.weight_kg = data["weight_kg"]
    if "height_cm" in data:
        if data["height_cm"] is not None and not (20 <= float(data["height_cm"]) <= 130):
            return jsonify({"error": "Tinggi tidak wajar (20-130 cm)"}), 400
        measurement.height_cm = data["height_cm"]
    if "head_circumference_cm" in data:
        if data["head_circumference_cm"] is not None and not (20 <= float(data["head_circumference_cm"]) <= 60):
            return jsonify({"error": "Lingkar kepala tidak wajar (20-60 cm)"}), 400
        measurement.head_circumference_cm = data["head_circumference_cm"]
    if "notes" in data:
        measurement.notes = data["notes"]
    db.session.commit()
    return jsonify(_enrich(measurement, child))


@growth_bp.route("/children/<int:child_id>/growth-latest", methods=["GET"])
def latest_growth_status(child_id):
    """Ringkasan status pertumbuhan terbaru, termasuk data lahir sebagai titik awal."""
    child = _owned_child(child_id)
    if not child:
        return jsonify({"error": "Anak tidak ditemukan"}), 404

    latest = (
        GrowthMeasurement.query.filter_by(child_id=child_id)
        .order_by(GrowthMeasurement.measured_date.desc())
        .first()
    )

    birth_status = {}
    age_at_birth = 0
    for key, mtype, field in [
        ("birth_weight_kg", "weight", "weight_kg"),
        ("birth_height_cm", "height", "height_cm"),
    ]:
        value = getattr(child, key)
        if value is not None:
            birth_status[f"{mtype}_who"] = evaluate_measurement(mtype, value, child.gender, age_at_birth)

    return jsonify({
        "birth": {
            "weight_kg": child.birth_weight_kg,
            "height_cm": child.birth_height_cm,
            **birth_status,
        },
        "latest": _enrich(latest, child) if latest else None,
    })