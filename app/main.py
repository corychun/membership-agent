from fastapi import FastAPI

from app.core.db import Base, engine

app = FastAPI()


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True}


# ✅ 延迟导入（防止 import 崩溃）
from app.api.orders import router as orders
from app.api.webhooks import router as webhooks
from app.api.deliveries import router as deliveries

app.include_router(orders)
app.include_router(webhooks)
app.include_router(deliveries)
