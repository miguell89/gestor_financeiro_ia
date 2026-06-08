import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    APP_ENV = os.getenv("APP_ENV", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    DATABASE_URL = os.getenv("DATABASE_URL", "")
    DATABASE_PATH = BASE_DIR / os.getenv("DATABASE_PATH", "data/gestor_financeiro.db")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_MODE = os.getenv("TELEGRAM_MODE", "polling")
    TELEGRAM_ALLOWED_USER_ID = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    ASSISTANT_TONE = os.getenv("ASSISTANT_TONE", "divertido")
    ALERT_HOUR = int(os.getenv("ALERT_HOUR", "8"))
    ADMIN_NAME = os.getenv("ADMIN_NAME", "Administrador")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@gestor.local")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
    ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID", "")
    SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "1" if os.getenv("APP_ENV", "development") != "production" else "0") == "1"


settings = Settings()
