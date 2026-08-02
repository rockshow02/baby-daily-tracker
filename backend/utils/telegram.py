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