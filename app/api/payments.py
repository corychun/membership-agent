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


PRICE_MAP_USD = {
    "GPT_ACTIVATE_1M": 20,
    "GPT_ACTIVATE_3M": 55,
    "GPT_TEAM_1M": 25,

    "CLAUDE_ACTIVATE_1M": 20,
    "CLAUDE_ACTIVATE_3M": 58,

    "MJ_BASIC_1M": 12,
    "MJ_STANDARD_1M": 18,
    "MJ_PRO_1M": 30,

    "GEMINI_PRO_1M": 10,
    "PERPLEXITY_PRO_1M": 12,
    "CURSOR_PRO_1M": 15,

    "AI_BUNDLE_1M": 30,

    # 兼容旧产品
    "GPT": 20,
    "VIP": 20,
    "CLAUDE": 20,
    "MJ": 20,
}


def _get_order_by_order_no(db: Session, order_no: str) -> Order:
    order = db.query(Order).filter(Order.order_no == order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def _is_paid(status: str | None) -> bool:
    return str(status or "").lower() in {"finished", "paid", "completed", "success"}


@router.post("/checkout")
def nowpayments_checkout(payload: CheckoutRequest, db: Session = Depends(get_db)):
    order = _get_order_by_order_no(db, payload.order_no)

    if _is_paid(order.payment_status):
        raise HTTPException(status_code=400, detail="Order already paid")

    product_code = str(order.product_code or "").upper()
    amount_usd = PRICE_MAP_USD.get(product_code, 20)

    # 兼容 nowpayments_service.py 读取 order.amount_usd
    order.amount_usd = amount_usd

    try:
        invoice = create_invoice(order=order, pay_currency=payload.pay_currency)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    order.payment_status = "waiting"
    order.status = "pending_payment"

    external_id = (
        invoice.get("id")
        or invoice.get("invoice_id")
        or invoice.get("payment_id")
    )

    if external_id and hasattr(order, "external_payment_id"):
        order.external_payment_id = str(external_id)

    db.add(order)
    db.commit()
    db.refresh(order)

    invoice_url = invoice.get("invoice_url") or invoice.get("url")

    return {
        "provider": "nowpayments",
        "order_no": order.order_no,
        "payment_status": order.payment_status,
        "invoice_id": invoice.get("id") or invoice.get("invoice_id"),
        "invoice_url": invoice_url,
        "payment_url": invoice_url,
        "pay_currency": payload.pay_currency,
        "amount_usd": amount_usd,
        "raw": invoice,
    }


@router.post("/mock-checkout")
def legacy_mock_checkout(payload: CheckoutRequest, db: Session = Depends(get_db)):
    return nowpayments_checkout(payload=payload, db=db)
