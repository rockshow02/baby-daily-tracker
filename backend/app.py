import os
from pathlib import Path

from flask import Flask, g, jsonify
from dotenv import load_dotenv

# Muat file environment backend sebelum config.py dievaluasi. Config menyimpan
# beberapa nilai sebagai atribut class saat module di-import, jadi pemanggilan
# load_dotenv setelah import config akan terlambat. Path eksplisit membuat
# bootstrap tetap benar saat proses dijalankan dari working directory lain.
load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))

from config import Config, DevConfig, TestConfig
from extensions import db, cors
from utils.observability import (
    check_database_ok,
    configure_logging,
    register_error_handlers,
    register_request_hooks,
    resolve_app_version,
)


def create_app(config_overrides=None):
    """
    config_overrides: dict opsional, di-apply SETELAH config class biasa
    tapi SEBELUM db.init_app()/create_all() jalan — dipakai buat test yang
    butuh konfigurasi DB beda dari TestConfig biasa (mis. SQLite file
    sementara buat test konkurensi, lihat tests/test_concurrency.py).
    Nggak dipakai di jalur produksi/dev normal.
    """
    app = Flask(__name__)

    env = os.environ.get("FLASK_ENV", "development")
    if env == "testing":
        app.config.from_object(TestConfig)
    elif env == "development":
        app.config.from_object(DevConfig)
    else:
        app.config.from_object(Config)

    if config_overrides:
        app.config.update(config_overrides)

    # Exception yang nggak ketangkep HARUS selalu lewat handler kita sendiri
    # (respons 500 yang aman, nggak bocorin stack trace) — BUKAN cuma di
    # production. Flask default-nya nge-propagate exception ke pemanggil
    # kalau TESTING/DEBUG True (biar debugger interaktif kepanggil pas dev
    # server jalan beneran), tapi itu bikin test_client() ikut nge-raise
    # exception mentah alih-alih ngebalikin response — nggak konsisten
    # sama perilaku production. setdefault (bukan langsung timpa) biar
    # config_overrides tetep bisa eksplisit override ini kalau ada test
    # yang sengaja butuh perilaku propagate aslinya.
    app.config.setdefault("PROPAGATE_EXCEPTIONS", False)

    # Traceback MENTAH (bisa ngandung SQL/parameter/path/data user) di log
    # server CUMA nyala kalau operator SENGAJA nge-set env var ini — bukan
    # ngikutin DEBUG/FLASK_ENV (yang bisa aja kepasang True nggak sengaja
    # di staging) — lihat utils/observability.py:handle_unexpected_exception.
    # Default-nya False di MANA PUN, termasuk dev.
    app.config.setdefault(
        "OBSERVABILITY_LOG_RAW_TRACEBACKS",
        os.environ.get("OBSERVABILITY_LOG_RAW_TRACEBACKS", "false").strip().lower() in ("1", "true", "yes"),
    )

    # pastikan folder instance ada (buat SQLite)
    os.makedirs(os.path.join(app.root_path, "instance"), exist_ok=True)

    db.init_app(app)
    cors.init_app(
        app,
        supports_credentials=True,
        origins=os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173").split(","),
        # X-Request-ID di 2 daftar: allow_headers (biar browser boleh
        # NGIRIM-nya di preflight, kalau frontend eksplisit nge-set) dan
        # expose_headers (biar JS di browser boleh MEMBACA header respons
        # ini — tanpa Access-Control-Expose-Headers, browser nyembunyiin
        # header custom apa pun dari `fetch`/`XMLHttpRequest`, walau
        # secara teknis ada di respons). Lihat backend/docs/OBSERVABILITY.md.
        allow_headers=["Content-Type", "Authorization", "X-Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    logger = configure_logging(app)
    register_request_hooks(app, logger)
    register_error_handlers(app, logger)

    from routes.auth_routes import auth_bp
    from routes.children_routes import children_bp
    from routes.daily_log_routes import daily_log_bp
    from routes.extra_log_routes import extra_log_bp
    from routes.growth_routes import growth_bp
    from routes.health_routes import health_bp
    from routes.mood_milestone_routes import mood_milestone_bp
    from routes.stats_routes import stats_bp
    from routes.report_routes import report_bp
    from routes.backup_routes import backup_bp
    from routes.article_routes import article_bp
    from routes.admin_routes import admin_bp
    from routes.audit_routes import audit_bp
    from routes.insights_routes import insights_bp
    from routes.reminder_routes import reminder_bp
    from routes.medication_schedule_routes import medication_schedule_bp
    from routes.medical_profile_routes import medical_profile_bp
    from routes.doctor_consultation_routes import doctor_consultation_bp
    from routes.caregiver_handover_routes import caregiver_handover_bp
    from routes.privacy_routes import privacy_bp
    from routes.memory_journal_routes import memory_journal_bp
    from routes.development_timeline_routes import development_timeline_bp
    from routes.monthly_story_routes import monthly_story_bp
    from routes.memory_storage_routes import memory_storage_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(children_bp, url_prefix="/api")
    app.register_blueprint(daily_log_bp, url_prefix="/api")
    app.register_blueprint(extra_log_bp, url_prefix="/api")
    app.register_blueprint(growth_bp, url_prefix="/api")
    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(mood_milestone_bp, url_prefix="/api")
    app.register_blueprint(stats_bp, url_prefix="/api")
    app.register_blueprint(report_bp, url_prefix="/api")
    app.register_blueprint(backup_bp, url_prefix="/api")
    app.register_blueprint(article_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/api")
    app.register_blueprint(audit_bp, url_prefix="/api")
    app.register_blueprint(insights_bp, url_prefix="/api")
    app.register_blueprint(reminder_bp, url_prefix="/api")
    app.register_blueprint(medication_schedule_bp, url_prefix="/api")
    app.register_blueprint(medical_profile_bp, url_prefix="/api")
    app.register_blueprint(doctor_consultation_bp, url_prefix="/api")
    app.register_blueprint(caregiver_handover_bp, url_prefix="/api")
    app.register_blueprint(privacy_bp, url_prefix="/api")
    app.register_blueprint(memory_journal_bp, url_prefix="/api")
    app.register_blueprint(development_timeline_bp, url_prefix="/api")
    app.register_blueprint(monthly_story_bp, url_prefix="/api")
    app.register_blueprint(memory_storage_bp, url_prefix="/api")

    with app.app_context():
        db.create_all()

    @app.route("/api/health")
    def health():
        """
        Endpoint publik, TANPA autentikasi, murah — dipanggil monitoring
        eksternal ATAU scripts/post_deploy_smoke_test.py. Cuma baca 1 baris
        `sqlite_master` (bukan PRAGMA integrity_check penuh) dan TIDAK
        PERNAH membocorkan tipe/path database, nama tabel, jumlah record,
        hostname, environment variable, atau detail exception mentah —
        lihat backend/docs/OBSERVABILITY.md buat kontrak lengkapnya.
        """
        request_id = getattr(g, "request_id", None) or "unknown"
        ok, category = check_database_ok(app)
        if ok:
            return jsonify(
                {
                    "status": "ok",
                    "database": "ok",
                    "version": resolve_app_version(),
                    "request_id": request_id,
                }
            )
        # category ("timeout"/"error") CUMA salah satu dari 2 nilai aman —
        # nempel ke log ringkasan request (lewat after_request hook di
        # utils/observability.py), TIDAK PERNAH ke respons klien di bawah.
        if category:
            g.db_check_category = category
        return (
            jsonify({"status": "degraded", "database": "unavailable", "request_id": request_id}),
            503,
        )

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000, host="0.0.0.0")  # host=0.0.0.0 biar bisa diakses dari HP di WiFi yang sama
