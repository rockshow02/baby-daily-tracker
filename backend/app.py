import os
from flask import Flask
from dotenv import load_dotenv

from config import Config, DevConfig
from extensions import db, cors

load_dotenv()


def create_app():
    app = Flask(__name__)

    env = os.environ.get("FLASK_ENV", "development")
    app.config.from_object(DevConfig if env == "development" else Config)

    # pastikan folder instance ada (buat SQLite)
    os.makedirs(os.path.join(app.root_path, "instance"), exist_ok=True)

    db.init_app(app)
    cors.init_app(
        app,
        supports_credentials=True,
        origins=os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173").split(","),
    )

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

    with app.app_context():
        db.create_all()

    @app.route("/api/health")
    def health():
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000, host="0.0.0.0")  # host=0.0.0.0 biar bisa diakses dari HP di WiFi yang sama