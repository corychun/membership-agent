from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order
from app.schemas.payment import MockWebhookRequest
from app.services.payment_service import mark_payment_status
from app.services.delivery_service import create_delivery_task

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/mock-payment")
def mock_payment_webhook(payload: MockWebhookRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == payload.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    order = mark_payment_status(db, order, payload.status)

    if payload.status == "paid" and order.review_status == "not_required":
        create_delivery_task(db, order, "manual_invite")

    return {
        "order_id": str(order.id),
        "status": order.status,
        "payment_status": order.payment_status,
        "delivery_status": order.delivery_status,
        "review_status": order.review_status,
    }
