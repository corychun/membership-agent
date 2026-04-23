from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.db import get_db
from app.models.entities import Order
from app.services.nowpayments_service import create_invoice

router = APIRouter(prefix="/payments", tags=["payments"])


class CheckoutRequest(BaseModel):
    order_no: str
    pay_currency: str = "usdttrc20"


def _get_order_by_order_no(db: Session, order_no: str) -> Order:
    order = db.query(Order).filter(Order.order_no == order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/checkout")
def nowpayments_checkout(payload: CheckoutRequest, db: Session = Depends(get_db)):
    order = _get_order_by_order_no(db, payload.order_no)

    if order.payment_status == "finished":
        raise HTTPException(status_code=400, detail="Order already paid")

    # ✅ 🔥 核心修复：补一个价格（先写死 1 美元）
    if not hasattr(order, "amount_usd"):
        order.amount_usd = 1

    try:
        invoice = create_invoice(order=order, pay_currency=payload.pay_currency)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    order.payment_status = "waiting"

    external_id = (
        invoice.get("id")
        or invoice.get("invoice_id")
        or invoice.get("payment_id")
    )

    if external_id:
        order.external_payment_id = str(external_id)

    db.add(order)
    db.commit()
    db.refresh(order)

    return {
        "provider": "nowpayments",
        "order_no": order.order_no,
        "payment_status": order.payment_status,
        "invoice_id": invoice.get("id") or invoice.get("invoice_id"),
        "invoice_url": invoice.get("invoice_url") or invoice.get("url"),
        "pay_currency": payload.pay_currency,
        "raw": invoice,
    }


@router.post("/mock-checkout")
def legacy_mock_checkout(payload: CheckoutRequest, db: Session = Depends(get_db)):
    return nowpayments_checkout(payload=payload, db=db)
