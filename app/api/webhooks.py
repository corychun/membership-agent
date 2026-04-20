import os
import stripe
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy.orm import Session
from app.core.db import SessionLocal
from app.models.entities import Order

router = APIRouter()

endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        order_id = session["metadata"].get("order_id")

        db: Session = SessionLocal()

        try:
            order = db.query(Order).filter(Order.id == order_id).first()

            if order:
                order.payment_status = "paid"
                order.status = "paid"
                db.commit()
        finally:
            db.close()

    return {"ok": True}
