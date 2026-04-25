from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core.db import Base, engine
from app.api.orders import router as orders
from app.api.payments import router as payments
from app.api.webhooks import router as webhooks
from app.api.deliveries import router as deliveries
from app.api.inventory import router as inventory_router
from app.api.admin import router as admin_router

app = FastAPI(title="membership-agent", version="1.0.0")


@app.on_event("startup")
def init():
    Base.metadata.create_all(bind=engine)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"
ADMIN_FILE = STATIC_DIR / "admin.html"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def root():
    if INDEX_FILE.exists():
        return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/admin-page")
def admin_page():
    if ADMIN_FILE.exists():
        return HTMLResponse(ADMIN_FILE.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>admin.html not found</h1>")


app.include_router(orders)
app.include_router(payments)
app.include_router(webhooks)
app.include_router(deliveries)
app.include_router(inventory_router)
app.include_router(admin_router)
