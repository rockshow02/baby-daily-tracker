import os
from flask import Flask, g, jsonify
from dotenv import load_dotenv

from config import Config, DevConfig, TestConfig
from extensions import db, cors
from utils.observability import (
    check_database_ok,
    configure_logging,
    register_error_handlers,
    register_request_hooks,
    resolve_app_version,
)

load_dotenv()


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

    # pastikan folder instance ada (buat SQLite)
    os.makedirs(os.path.join(app.root_path, "instance"), exist_ok=True)

    db.init_app(app)
    cors.init_app(
        app,
        supports_credentials=True,
        origins=os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173").split(","),
        allow_headers=["Content-Type", "Authorization", "X-Idempotency-Key"],
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

    with app.app_context():
        db.create_all()

    @app.route("/api/health")
    def health():
        """
        Endpoint publik, TANPA autentikasi, murah — dipanggil monitoring
        eksternal ATAU scripts/post_deploy_smoke_test.py. Cuma SELECT 1
        (bukan PRAGMA integrity_check penuh) dan TIDAK PERNAH membocorkan
        tipe/path database, nama tabel, jumlah record, hostname, environment
        variable, atau detail exception mentah — lihat backend/docs/
        OBSERVABILITY.md buat kontrak lengkapnya.
        """
        request_id = getattr(g, "request_id", None) or "unknown"
        if check_database_ok(app):
            return jsonify(
                {
                    "status": "ok",
                    "database": "ok",
                    "version": resolve_app_version(),
                    "request_id": request_id,
                }
            )
        return (
            jsonify({"status": "degraded", "database": "unavailable", "request_id": request_id}),
            503,
        )

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000, host="0.0.0.0")  # host=0.0.0.0 biar bisa diakses dari HP di WiFi yang sama