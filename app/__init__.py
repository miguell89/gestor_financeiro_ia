from datetime import timedelta

from flask import Flask

from config.settings import settings


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = settings.APP_ENV == "production"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

    from app.routes.web import web_bp

    app.register_blueprint(web_bp)
    return app
