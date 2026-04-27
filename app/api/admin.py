import os
import traceback

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order
from app.services.delivery import mark_paid_and_deliver

router = APIRouter(prefix="/admin", tags=["admin"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ConfirmPaidRequest(BaseModel):
    admin_password: str
    order_no: str


def check_admin_password(password: str | None):
    expected = os.getenv("ADMIN_PASSWORD", "123456")
    if password != expected:
        raise HTTPException(status_code=401, detail="Invalid admin password")


def check_admin_login(username: str | None, password: str | None):
    expected_user = os.getenv("ADMIN_USERNAME", "chun")
    expected_pwd = os.getenv("ADMIN_PASSWORD", "Ch011290_")

    if username != expected_user or password != expected_pwd:
        raise HTTPException(status_code=401, detail="管理员账号或密码错误")


def norm(value):
    return str(value or "").lower()


def is_delivered(order: Order) -> bool:
    return norm(order.delivery_status) in {"delivered", "completed", "success", "sent"}


def can_manual_confirm(order: Order) -> bool:
    if is_delivered(order):
        return False

    return norm(order.payment_status) in {
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


@router.post("/login")
def admin_login(payload: LoginRequest):
    check_admin_login(payload.username, payload.password)
    return {"ok": True, "msg": "login success"}


@router.get("/orders")
def list_orders(
    admin_password: str = Query(...),
    db: Session = Depends(get_db),
):
    check_admin_password(admin_password)

    orders = db.query(Order).order_by(Order.id.desc()).limit(100).all()

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

    try:
        result = mark_paid_and_deliver(db, order)
        db.refresh(order)

        return {
            "ok": True,
            "msg": "paid + delivered",
            "order_no": order.order_no,
            "delivery_content": order.delivery_content,
            "result": result,
        }

    except Exception as e:
        db.rollback()
        print(traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"发货失败：{str(e)}")
