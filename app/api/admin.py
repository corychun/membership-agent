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

    result = mark_paid_and_deliver(db, order)

    return {
        "ok": True,
        "msg": "paid + delivered",
        "order_no": order.order_no,
        "result": result,
    }
