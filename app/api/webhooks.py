import hashlib
import hmac
import json
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class MockPaymentRequest(BaseModel):
    order_id: str
    status: str = "paid"


def _normalize_payment_status(raw_status: Optional[str]) -> str:
    if not raw_status:
        return "waiting"

    s = raw_status.lower().strip()

    if s in {"finished", "confirmed", "paid", "success"}:
        return "finished"

    if s in {"failed", "expired", "cancelled", "canceled"}:
        return "failed"

    return "waiting"


def _apply_order_status(order: Order, payment_status: str) -> None:
    if payment_status == "finished":
        order.payment_status = "finished"
        order.status = "completed"
    elif payment_status == "failed":
        order.payment_status = "failed"
        order.status = "failed"
    else:
        order.payment_status = "waiting"
        order.status = "created"


@router.post("/nowpayments")
async def nowpayments_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    data = json.loads(raw_body.decode("utf-8") or "{}")

    ipn_secret = os.getenv("NOWPAYMENTS_IPN_SECRET", "").strip()
    signature = request.headers.get("x-nowpayments-sig", "").strip()

    if ipn_secret:
        expected_sig = hmac.new(
            ipn_secret.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        if not signature or not hmac.compare_digest(signature, expected_sig):
            raise HTTPException(status_code=401, detail="Invalid IPN signature")

    order_id = data.get("order_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="Missing order_id")

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    payment_status = _normalize_payment_status(data.get("payment_status"))
    _apply_order_status(order, payment_status)

    db.commit()
    db.refresh(order)

    return {
        "ok": True,
        "order_id": str(order.id),
        "payment_status": order.payment_status,
        "status": order.status,
    }


@router.post("/mock-payment")
def mock_payment(payload: MockPaymentRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == payload.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    payment_status = _normalize_payment_status(payload.status)
    _apply_order_status(order, payment_status)

    db.commit()
    db.refresh(order)

    return {
        "ok": True,
        "message": "mock payment success",
        "order_id": str(order.id),
        "payment_status": order.payment_status,
        "status": order.status,
    }
