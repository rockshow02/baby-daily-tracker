"""
Helper kirim pesan lewat Telegram Bot API. Nggak pakai n8n atau layanan
pihak ketiga lain — cuma HTTP request biasa ke api.telegram.org, gratis
selamanya, nggak ada limit eksekusi kayak n8n Cloud.

Cara dapetin BOT_TOKEN:
  1. Chat ke @BotFather di Telegram
  2. Kirim /newbot, ikutin instruksinya (kasih nama bot)
  3. BotFather bakal kasih token, contoh: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
  4. Set token itu sebagai environment variable TELEGRAM_BOT_TOKEN
"""
import os
import requests

TELEGRAM_API_BASE = "https://api.telegram.org"


def send_telegram_message(chat_id, text):
    """Return True kalau berhasil, False kalau gagal (chat_id salah, token nggak ada, dll)."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token or not chat_id:
        return False

    try:
        resp = requests.post(
            f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return resp.status_code == 200 and resp.json().get("ok", False)
    except requests.RequestException:
        return False


def notify_other_caregivers(child, actor_user_id, message):
    """
    Kirim notifikasi instan ke SEMUA pengasuh anak ini KECUALI yang lagi
    ngelakuin aksinya sendiri (actor_user_id) — biar nggak dapet notif
    soal catatan yang dia buat sendiri. Dipakai buat kasih tau real-time
    kalau ada pengasuh lain baru catat sesuatu, biar nggak dobel-catat
    pas 2 orang pegang HP bersamaan.

    DEFAULT MATI — biar nggak kebanyakan notif tiap catat apa aja. Nyalain
    kapan aja tanpa ubah kode, cukup set environment variable:
        ENABLE_INSTANT_CAREGIVER_NOTIF=true
    (Ini TERPISAH dari reminder harian/ringkasan Telegram yang lain —
    matiin ini nggak ngaruh ke reminder harian, itu tetep jalan normal.)

    "Best effort" — gagal kirim (chat_id kosong, Telegram lagi down, dll)
    nggak bikin request utama (nyimpen log) ikut gagal.
    """
    if os.environ.get("ENABLE_INSTANT_CAREGIVER_NOTIF", "").lower() != "true":
        return

    # import di dalam fungsi biar nggak circular import (models import db,
    # dan modul ini dipakai dari banyak route)
    from models import ChildCaregiver, User

    try:
        caregivers = (
            User.query.join(ChildCaregiver, ChildCaregiver.user_id == User.id)
            .filter(
                ChildCaregiver.child_id == child.id,
                ChildCaregiver.user_id != actor_user_id,
                User.telegram_chat_id.isnot(None),
            )
            .all()
        )
        for user in caregivers:
            send_telegram_message(user.telegram_chat_id, message)
    except Exception:
        # jangan sampai gagal notif bikin request utama ikut error
        pass