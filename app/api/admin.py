import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order
from app.services.delivery import mark_paid_and_deliver

router = APIRouter(prefix="/admin", tags=["admin"])


class ConfirmPaidRequest(BaseModel):
    admin_password: str
    order_no: str


def check_admin_password(password: str | None):
    expected = os.getenv("ADMIN_PASSWORD", "123456")
    if password != expected:
        raise HTTPException(status_code=401, detail="Invalid admin password")


def is_delivered(order: Order) -> bool:
    return str(order.delivery_status or "").lower() in {
        "delivered",
        "completed",
        "success",
        "sent",
    }


def can_manual_confirm(order: Order) -> bool:
    """
    人工确认收款允许的状态：
    - waiting
    - pending
    - pending_payment
    - unpaid
    - paid
    - finished

    但如果已经发货，禁止重复发货。
    """
    if is_delivered(order):
        return False

    payment_status = str(order.payment_status or "").lower()

    return payment_status in {
        "waiting",
        "pending",
        "pending_payment",
        "unpaid",
        "paid",
        "finished",
        "confirmed",
        "",
        "none",
    }


@router.get("/orders")
def list_orders(
    admin_password: str = Query(...),
    db: Session = Depends(get_db),
):
    check_admin_password(admin_password)

    orders = (
        db.query(Order)
        .order_by(Order.id.desc())
        .limit(100)
        .all()
    )

    return {
        "items": [
            {
                "id": o.id,
                "order_no": o.order_no,
                "product_code": o.product_code,
                "customer_email": o.customer_email,
                "payment_status": o.payment_status,
                "status": o.status,
                "delivery_status": o.delivery_status,
                "delivery_content": o.delivery_content,
                "created_at": str(o.created_at) if o.created_at else None,
                "can_confirm": can_manual_confirm(o),
            }
            for o in orders
        ]
    }


@router.post("/orders/confirm-paid")
def confirm_paid_and_deliver(
    payload: ConfirmPaidRequest,
    db: Session = Depends(get_db),
):
    check_admin_password(payload.admin_password)

    order = db.query(Order).filter(Order.order_no == payload.order_no).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if is_delivered(order):
        return {
            "ok": True,
            "msg": "already delivered",
            "order_no": order.order_no,
            "delivery_content": order.delivery_content,
        }

    if not can_manual_confirm(order):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态不允许发货：payment_status={order.payment_status}, delivery_status={order.delivery_status}",
        )

    # 人工确认收款后，先标记为已支付，再发货
    order.payment_status = "paid"
    order.status = "paid"
    db.commit()
    db.refresh(order)

    result = mark_paid_and_deliver(db, order)

    return {
        "ok": True,
        "msg": "paid + delivered",
        "order_no": order.order_no,
        "result": result,
        "delivery_content": getattr(order, "delivery_content", None),
    }
