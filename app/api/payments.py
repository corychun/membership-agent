from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order
from app.services.nowpayments_service import create_invoice

router = APIRouter(prefix="/payments", tags=["payments"])


def _get_order(db: Session, order_id: str):
    try:
        order_uuid = UUID(order_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order_id")

    order = db.query(Order).filter(Order.id == order_uuid).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/checkout")
def nowpayments_checkout(data: dict, db: Session = Depends(get_db)):
    order_id = data.get("order_id")
    pay_currency = data.get("pay_currency", "usdttrc20")

    if not order_id:
        raise HTTPException(status_code=400, detail="order_id is required")

    order = _get_order(db, order_id)

    if getattr(order, "payment_status", None) == "paid":
        raise HTTPException(status_code=400, detail="Order already paid")

    try:
        invoice = create_invoice(order=order, pay_currency=pay_currency)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    order.payment_status = "waiting"
    db.commit()

    return {
        "provider": "nowpayments",
        "order_id": str(order.id),
        "payment_status": order.payment_status,
        "invoice_id": invoice.get("id") or invoice.get("invoice_id"),
        "invoice_url": invoice.get("invoice_url") or invoice.get("url"),
        "pay_currency": pay_currency,
        "raw": invoice,
    }


# 为了兼容你之前的接口名，保留旧入口
@router.post("/mock-checkout")
def legacy_mock_checkout(data: dict, db: Session = Depends(get_db)):
    return nowpayments_checkout(data=data, db=db)
