from fastapi import FastAPI
from app.core.db import Base, engine

from app.api.orders import router as orders
from app.api.webhooks import router as webhooks
from app.api.deliveries import router as deliveries

app = FastAPI()


@app.on_event("startup")
def init():
    Base.metadata.create_all(bind=engine)


app.include_router(orders)
app.include_router(webhooks)
app.include_router(deliveries)
