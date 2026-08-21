import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """
    Konfigurasi utama backend Baby Daily Tracker.
    SQLite lokal, session-based auth, siap deploy ke PythonAnywhere.
    """
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-ganti-di-production")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'tracker.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024  # 6MB, sedikit di atas limit foto 5MB

    SESSION_COOKIE_SAMESITE = "None"   # perlu None kalau frontend beda domain (Vercel <-> PythonAnywhere)
    SESSION_COOKIE_SECURE = True       # wajib True kalau SAMESITE=None (butuh HTTPS)
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)

    # Untuk dev lokal di http://localhost, override 2 baris di atas via .env:
    # SESSION_COOKIE_SAMESITE=Lax
    # SESSION_COOKIE_SECURE=False


class DevConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False


class TestConfig(Config):
    """Dipakai pytest — SQLite in-memory, jangan pernah nyentuh instance/tracker.db."""
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False