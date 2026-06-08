import os

from app import create_app
from app.database import init_db, seed_db
from app.services.finance_service import sync_all_paid_fixed_bills
from config.settings import settings

app = create_app()
init_db()
if settings.SEED_DEMO_DATA:
    seed_db()
sync_all_paid_fixed_bills()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=settings.APP_ENV != "production", use_reloader=False)
