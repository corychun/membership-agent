from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.db import Base, engine, SessionLocal
from app.core.admin_auth import seed_first_admin

from app.api.orders import router as orders
from app.api.payments import router as payments
from app.api.webhooks import router as webhooks
from app.api.deliveries import router as deliveries
from app.api.inventory import router as inventory_router
from app.api.admin import router as admin_router
from app.api.support import router as support_router
from app.api.support_ws import router as support_ws_router

app = FastAPI(title="membership-agent", version="1.0.0")


@app.on_event("startup")
def init():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        seed_first_admin(db)
    finally:
        db.close()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def root():
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True}


app.include_router(orders)
app.include_router(payments)
app.include_router(webhooks)
app.include_router(deliveries)
app.include_router(inventory_router)
app.include_router(admin_router)
app.include_router(support_router)
app.include_router(support_ws_router)
