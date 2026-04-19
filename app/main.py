from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, quote, orders, payments, webhooks, deliveries, chat
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


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


@app.get("/")
def home():
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))


@app.get("/frontend")
def frontend():
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))
