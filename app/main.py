from fastapi import FastAPI
from app.core.db import Base, engine

from app.api.orders import router as orders
from app.api.payments import router as payments
from app.api.webhooks import router as webhooks
from app.api.deliveries import router as deliveries

app = FastAPI(title="membership-agent", version="1.0.0")


@app.on_event("startup")
def init():
    Base.metadata.create_all(bind=engine)


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
