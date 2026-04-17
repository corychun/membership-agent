from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from app.core.db import Base, engine, SessionLocal
from app.api import admin, quote, orders, payments, webhooks, deliveries, chat
from app.services.catalog_service import seed_products
from app.core.config import settings
import app.models.entities  # noqa: F401


app = FastAPI(title=settings.app_name)

app.include_router(quote.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(webhooks.router)
app.include_router(deliveries.router)
app.include_router(chat.router)
app.include_router(admin.router)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def ensure_payment_columns() -> None:
    inspector = inspect(engine)
    if "payments" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("payments")}
    ddl = {
        "payment_method": "ALTER TABLE payments ADD COLUMN payment_method VARCHAR(30)",
        "network": "ALTER TABLE payments ADD COLUMN network VARCHAR(30)",
        "wallet_address": "ALTER TABLE payments ADD COLUMN wallet_address VARCHAR(255)",
        "amount_usdt": "ALTER TABLE payments ADD COLUMN amount_usdt NUMERIC(12, 2)",
        "tx_hash": "ALTER TABLE payments ADD COLUMN tx_hash VARCHAR(255)",
        "confirmed_at": "ALTER TABLE payments ADD COLUMN confirmed_at TIMESTAMP",
    }

    with engine.begin() as connection:
        for column_name, sql in ddl.items():
            if column_name not in existing_columns:
                connection.execute(text(sql))


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_payment_columns()
    db = SessionLocal()
    db.close()


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


@app.get("/")
def home():
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))


@app.get("/frontend")
def frontend():
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))
