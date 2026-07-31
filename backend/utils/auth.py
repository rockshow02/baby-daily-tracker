"""
Autentikasi cross-domain (Vercel <-> PythonAnywhere).

Cookie session biasa (SameSite=None) makin sering diblokir browser modern
buat request lintas domain (Safari ITP, mode privasi Chrome, dll) — efeknya
user kelihatan "logout" tiap refresh padahal datanya aman.

Solusinya: setelah login/register, backend kasih token yang di-generate
di sini. Frontend nyimpen token itu (localStorage) dan ngirim balik lewat
header "Authorization: Bearer <token>" di tiap request — nggak bergantung
sama sikap browser terhadap cookie lintas-domain sama sekali.

Cookie session tetap dipakai sebagai fallback (misal buat dev lokal yang
frontend-backend-nya satu domain), tapi token yang jadi andalan utama.
"""
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import current_app, session, request

TOKEN_MAX_AGE = 60 * 60 * 24 * 30  # 30 hari, samain kayak PERMANENT_SESSION_LIFETIME


def generate_token(user_id):
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    return s.dumps({"user_id": user_id})


def get_current_user_id():
    """Cek user_id dari header Authorization dulu, fallback ke session cookie."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        try:
            data = s.loads(token, max_age=TOKEN_MAX_AGE)
            return data.get("user_id")
        except (BadSignature, SignatureExpired):
            return None

    return session.get("user_id")