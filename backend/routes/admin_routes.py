"""
Endpoint buat memicu reminder Telegram dari luar — dipakai GitHub Actions
(scheduled workflow, gratis) sebagai pengganti PythonAnywhere Scheduled
Tasks (yang sekarang cuma buat akun berbayar / akun lama sebelum
15 Jan 2026).

Dilindungi secret key (bukan endpoint publik) — cuma bisa dipicu kalau
tau REMINDER_TRIGGER_SECRET-nya, biar nggak sembarang orang bisa nge-spam
kirim reminder ke semua user.
"""
import os

from flask import Blueprint, request, jsonify

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin/trigger-reminders", methods=["POST"])
def trigger_reminders():
    secret = request.headers.get("X-Reminder-Secret", "")
    expected = os.environ.get("REMINDER_TRIGGER_SECRET", "")

    if not expected or secret != expected:
        return jsonify({"error": "Unauthorized"}), 401

    # import di dalam fungsi biar nggak bikin circular import pas app.py
    # nge-load semua blueprint di create_app()
    from scripts.send_reminders import run_reminders
    result = run_reminders()
    return jsonify(result)