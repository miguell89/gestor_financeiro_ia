from flask import Flask

from config.settings import settings


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.SECRET_KEY

    from app.routes.web import web_bp

    app.register_blueprint(web_bp)
    return app
