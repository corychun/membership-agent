from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.db import get_db
from app.core.products import product_amount_usd, product_name, product_price_cny
from app.models.entities import Order
from app.services.nowpayments_service import create_invoice

router = APIRouter(prefix="/payments", tags=["payments"])


class CheckoutRequest(BaseModel):
    order_no: str
    pay_currency: str = "usdttrc20"


# 兼容旧代码可能直接导入 PRICE_MAP_USD。
# 新增/调价请优先修改 app/core/products.py。
PRICE_MAP_USD = {
    "GPT_ACTIVATE_1M": 20,
    "GPT_ACTIVATE_1Y": 240,
    "GPT_TEAM_1M": 25,
    "CLAUDE_ACTIVATE_1M": 20,
    "CLAUDE_ACTIVATE_1Y": 204,
    "MJ_BASIC_1M": 10,
    "MJ_STANDARD_1M": 30,
    "MJ_PRO_1M": 60,
    "MJ_MEGA_1M": 120,
    "GEMINI_PLUS_1M": 10,
    "GEMINI_PRO_1M": 19,
    "GEMINI_ULTRA_1M": 199,
    # 历史兼容
    "GPT_ACTIVATE_3M": 60,
    "CLAUDE_ACTIVATE_3M": 60,
    "GEMINI_PRO_OLD_1M": 10,
    "PERPLEXITY_PRO_1M": 12,
    "CURSOR_PRO_1M": 15,
    "AI_BUNDLE_1M": 30,
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
    amount_usd = product_amount_usd(product_code, PRICE_MAP_USD.get(product_code, 20))

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

    external_id = invoice.get("id") or invoice.get("invoice_id") or invoice.get("payment_id")

    if external_id and hasattr(order, "external_payment_id"):
        order.external_payment_id = str(external_id)

    db.add(order)
    db.commit()
    db.refresh(order)

    invoice_url = invoice.get("invoice_url") or invoice.get("url")

    return {
        "provider": "nowpayments",
        "order_no": order.order_no,
        "product_code": order.product_code,
        "product_name": product_name(order.product_code),
        "product_price_cny": product_price_cny(order.product_code, 0),
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
