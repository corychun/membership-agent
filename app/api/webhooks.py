import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.entities import Order
from app.services.nowpayments_service import verify_ipn_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _load_order(db: Session, raw_order_id: str):
    try:
        order_uuid = UUID(str(raw_order_id))
    except Exception:
        return None

    return db.query(Order).filter(Order.id == order_uuid).first()


@router.post("/nowpayments")
async def nowpayments_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-nowpayments-sig")

    if not verify_ipn_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid NOWPayments signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    order_id = (
        payload.get("order_id")
        or payload.get("orderid")
        or payload.get("purchase_id")
        or payload.get("purchaseid")
    )

    payment_status = str(
        payload.get("payment_status")
        or payload.get("paymentstatus")
        or payload.get("paymentStatus")
        or ""
    ).lower()

    if not order_id:
        raise HTTPException(status_code=400, detail="order_id not found in webhook payload")

    db: Session = SessionLocal()

    try:
        order = _load_order(db, order_id)

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # NOWPayments 典型状态：
        # waiting / confirming / confirmed / sending / finished / failed / refunded / expired
        if payment_status == "finished":
            order.payment_status = "paid"
            order.status = "completed"
            order.delivery_status = "ready"

        elif payment_status in {"confirming", "confirmed", "sending"}:
            order.payment_status = payment_status
            order.status = "processing"

        elif payment_status in {"failed", "expired", "refunded"}:
            order.payment_status = payment_status
            order.status = "payment_failed"

        elif payment_status == "waiting":
            order.payment_status = "waiting"
            order.status = "created"

        else:
            order.payment_status = payment_status or "unknown"

        db.commit()

        return {
            "ok": True,
            "order_id": str(order.id),
            "payment_status": order.payment_status,
            "status": order.status,
            "delivery_status": order.delivery_status,
        }

    finally:
        db.close()


# 本地调试备用：手动把订单改成 paid
@router.post("/mock-payment")
async def mock_payment(request: Request):
    payload = await request.json()
    order_id = payload.get("order_id")
    status = payload.get("status", "paid")

    if not order_id:
        raise HTTPException(status_code=400, detail="order_id is required")

    db: Session = SessionLocal()

    try:
        order = _load_order(db, order_id)

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if status == "paid":
            order.payment_status = "paid"
            order.status = "completed"
            order.delivery_status = "ready"
        else:
            order.payment_status = status
            order.status = "processing"

        db.commit()

        return {
            "ok": True,
            "order_id": str(order.id),
            "payment_status": order.payment_status,
            "status": order.status,
            "delivery_status": order.delivery_status,
        }

    finally:
        db.close()
