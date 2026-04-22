import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order
from app.services.delivery import mark_paid_and_deliver
from app.services.nowpayments_service import verify_ipn_signature

router = APIRouter(tags=["webhooks"])


class MockPaymentRequest(BaseModel):
    order_no: str


def _normalize_payment_status(raw_status: Optional[str]) -> str:
    if not raw_status:
        return "waiting"

    s = str(raw_status).lower().strip()

    if s in {"finished", "confirmed", "paid", "success"}:
        return "finished"

    if s in {"failed", "expired", "cancelled", "canceled"}:
        return "failed"

    return "waiting"


@router.post("/webhooks/mock-payment")
def mock_payment(payload: MockPaymentRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter_by(order_no=payload.order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="order not found")

    result = mark_paid_and_deliver(db, order)

    return {
        "msg": "paid + delivered",
        "result": result,
    }


@router.post("/webhooks/nowpayments")
async def nowpayments_webhook(
    request: Request,
    x_nowpayments_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()

    try:
        data = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not verify_ipn_signature(raw_body, x_nowpayments_sig):
        raise HTTPException(status_code=401, detail="Invalid IPN signature")

    order_no = data.get("order_id")
    if not order_no:
        raise HTTPException(status_code=400, detail="Missing order_id")

    order = db.query(Order).filter(Order.order_no == str(order_no)).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    payment_status = _normalize_payment_status(data.get("payment_status"))

    external_id = data.get("payment_id") or data.get("invoice_id") or data.get("id")
    if external_id:
        order.external_payment_id = str(external_id)

    if payment_status == "finished":
        result = mark_paid_and_deliver(db, order)
        db.refresh(order)
        return {
            "ok": True,
            "source": "nowpayments",
            "order_no": order.order_no,
            "payment_status": order.payment_status,
            "status": order.status,
            "delivery_status": order.delivery_status,
            "delivery_result": result,
        }

    if payment_status == "failed":
        order.payment_status = "failed"
        order.status = "failed"
    else:
        order.payment_status = "waiting"
        if order.status != "completed":
            order.status = "pending_payment"

    db.add(order)
    db.commit()
    db.refresh(order)

    return {
        "ok": True,
        "source": "nowpayments",
        "order_no": order.order_no,
        "payment_status": order.payment_status,
        "status": order.status,
        "delivery_status": order.delivery_status,
    }
