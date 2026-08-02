from flask import Blueprint, request, jsonify, session

from extensions import db
from models import User
from utils.auth import generate_token, get_current_user_id
from utils.telegram import send_telegram_message

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not name or not email or not password:
        return jsonify({"error": "Nama, email, dan password wajib diisi"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password minimal 6 karakter"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email sudah terdaftar"}), 409

    user = User(name=name, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    session.permanent = True
    session["user_id"] = user.id

    result = user.to_dict()
    result["token"] = generate_token(user.id)
    return jsonify(result), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Email atau password salah"}), 401

    session.permanent = True
    session["user_id"] = user.id

    result = user.to_dict()
    result["token"] = generate_token(user.id)
    return jsonify(result)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    return jsonify({"success": True})


@auth_bp.route("/me", methods=["GET"])
def me():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401
    user = User.query.get(user_id)
    if not user:
        session.pop("user_id", None)
        return jsonify({"error": "Belum login"}), 401
    return jsonify(user.to_dict())


@auth_bp.route("/me", methods=["PUT"])
def update_me():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "Belum login"}), 401

    data = request.get_json() or {}
    if "name" in data:
        name = data["name"].strip()
        if not name:
            return jsonify({"error": "Nama tidak boleh kosong"}), 400
        user.name = name
    if "telegram_chat_id" in data:
        user.telegram_chat_id = (data["telegram_chat_id"] or "").strip() or None
    db.session.commit()
    return jsonify(user.to_dict())


@auth_bp.route("/me/telegram/test", methods=["POST"])
def test_telegram():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "Belum login"}), 401
    if not user.telegram_chat_id:
        return jsonify({"error": "Chat ID Telegram belum diisi"}), 400

    ok = send_telegram_message(
        user.telegram_chat_id,
        f"👋 Halo {user.name}! Notifikasi Baby Daily Tracker berhasil tersambung.",
    )
    if not ok:
        return jsonify({"error": "Gagal kirim pesan. Cek lagi Chat ID-nya, atau pastikan kamu udah pernah kirim pesan ke bot-nya dulu."}), 400
    return jsonify({"success": True})


@auth_bp.route("/me/password", methods=["PUT"])
def change_password():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"error": "Belum login"}), 401
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "Belum login"}), 401

    data = request.get_json() or {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    if not user.check_password(current_password):
        return jsonify({"error": "Password saat ini salah"}), 400
    if len(new_password) < 6:
        return jsonify({"error": "Password baru minimal 6 karakter"}), 400

    user.set_password(new_password)
    db.session.commit()
    return jsonify({"success": True})