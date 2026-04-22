from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.db import Base, engine

from app.api.orders import router as orders
from app.api.payments import router as payments
from app.api.webhooks import router as webhooks
from app.api.deliveries import router as deliveries
from app.api.inventory import router as inventory_router

app = FastAPI(title="membership-agent", version="1.0.0")


@app.on_event("startup")
def init():
    # 开发调试阶段用：清空旧表并按最新 models 重建
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
