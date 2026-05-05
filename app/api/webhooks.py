import json
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect

from app.core.db import get_db
from app.models.entities import Order, RenewalTask
from app.core.products import is_activation_product, product_period_days
from datetime import datetime, timedelta
from app.services.nowpayments_service import verify_ipn_signature

router = APIRouter(tags=["webhooks"])


class MockPaymentRequest(BaseModel):
    order_no: str


def _normalize_payment_status(raw_status: Optional[str]) -> str:
    if not raw_status:
        return "waiting"

    s = str(raw_status).lower().strip()

    if s in {
        "finished",
        "confirmed",
        "paid",
        "success",
        "partially_paid",
    }:
        return "finished"

    if s in {
        "failed",
        "expired",
        "cancelled",
        "canceled",
        "refunded",
    }:
        return "failed"

    return "waiting"


def _mark_order_paid_processing(db: Session, order: Order):
    """
    纯代开通模式：
    支付成功后，只进入待开通/处理中。
    加了幂等保护，重复回调不会重复覆盖已完成订单。
    """
    if str(order.delivery_status or "").lower() in {"delivered", "completed", "sent", "success"}:
        return {
            "ok": True,
            "idempotent": True,
            "order_no": order.order_no,
            "payment_status": order.payment_status,
            "status": order.status,
            "delivery_status": order.delivery_status,
            "delivery_content": order.delivery_content,
        }

    already_processing = (
        str(order.payment_status or "").lower() in {"paid", "finished", "confirmed", "success"}
        and str(order.delivery_status or "").lower() == "processing"
    )

    order.payment_status = "paid"
    order.status = "paid"
    order.delivery_status = "processing"

    if not order.delivery_content:
        order.delivery_content = "已确认收款，订单已进入代开通流程，请等待开通完成通知。"

    if is_activation_product(order.product_code):
        task = db.query(RenewalTask).filter(RenewalTask.order_no == order.order_no).first()
        if not task:
            period_days = product_period_days(order.product_code, 30)
            task = RenewalTask(
                order_no=order.order_no,
                product_code=order.product_code,
                customer_email=order.customer_email,
                period_days=period_days,
                due_at=(order.created_at or datetime.utcnow()) + timedelta(days=period_days),
                status="processing",
                notes="支付回调后进入代开通流程",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(task)
        else:
            task.status = "processing" if task.status not in {"active", "closed", "cancelled"} else task.status
            task.updated_at = datetime.utcnow()
            db.add(task)

    db.add(order)
    db.commit()
    db.refresh(order)

    return {
        "ok": True,
        "idempotent": already_processing,
        "order_no": order.order_no,
        "payment_status": order.payment_status,
        "status": order.status,
        "delivery_status": order.delivery_status,
        "delivery_content": order.delivery_content,
    }


@router.post("/webhooks/mock-payment")
def mock_payment(payload: MockPaymentRequest, db: Session = Depends(get_db)):
    """
    免费测试接口：
    不用真实付款，直接把订单改成 paid + processing。
    """
    order = db.query(Order).filter_by(order_no=payload.order_no).first()

    if not order:
        raise HTTPException(status_code=404, detail="order not found")

    result = _mark_order_paid_processing(db, order)

    return {
        "msg": "mock paid + processing",
        "result": result,
    }


@router.post("/webhooks/nowpayments")
async def nowpayments_webhook(
    request: Request,
    x_nowpayments_sig: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """
    NOWPayments IPN 回调：
    只负责确认付款并把订单进入代开通流程。
    """

    try:
        body_bytes = b""

        async for chunk in request.stream():
            body_bytes += chunk

    except ClientDisconnect:
        return {
            "ok": False,
            "error": "client disconnected while reading webhook body",
        }

    if not body_bytes:
        raise HTTPException(status_code=400, detail="Empty webhook body")

    try:
        data = json.loads(body_bytes.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not verify_ipn_signature(body_bytes, x_nowpayments_sig):
        raise HTTPException(status_code=401, detail="Invalid IPN signature")

    order_no = data.get("order_id")

    if not order_no:
        raise HTTPException(status_code=400, detail="Missing order_id")

    order = db.query(Order).filter(Order.order_no == str(order_no)).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    external_id = (
        data.get("payment_id")
        or data.get("invoice_id")
        or data.get("id")
    )

    if external_id and hasattr(order, "external_payment_id"):
        order.external_payment_id = str(external_id)

    payment_status = _normalize_payment_status(data.get("payment_status"))

    if payment_status == "finished":
        result = _mark_order_paid_processing(db, order)

        return {
            "ok": True,
            "source": "nowpayments",
            "order_no": order.order_no,
            "payment_status": order.payment_status,
            "status": order.status,
            "delivery_status": order.delivery_status,
            "result": result,
        }

    if payment_status == "failed":
        order.payment_status = "failed"
        order.status = "failed"

    else:
        order.payment_status = "waiting"
        if order.status not in {"paid", "completed"}:
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
