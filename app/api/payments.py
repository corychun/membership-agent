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
    # 当前金额用于 NOWPayments price_amount。
    # pay_currency 为 usdttrc20 时，用户实际约按以下 USDT 数额付款。
    # 为避免小数和汇率波动，这里统一使用整数价。

    # ChatGPT
    "GPT_PLUS_1M": 25,
    "GPT_ACTIVATE_1M": 26,
    "GPT_ACTIVATE_1Y": 270,
    "GPT_PLUS_1Y": 270,
    "GPT_TEAM_1M": 36,
    "GPT_PRO_5X_1M": 125,
    "GPT_PRO_20X_1M": 239,

    # Claude
    "CLAUDE_PRO_1M": 28,
    "CLAUDE_ACTIVATE_1M": 26,
    "CLAUDE_ACTIVATE_1Y": 270,
    "CLAUDE_PRO_1Y": 270,
    "CLAUDE_MAX_5X_1M": 125,
    "CLAUDE_MAX_20X_1M": 239,

    # Midjourney
    "MJ_BASIC_1M": 20,
    "MJ_STANDARD_1M": 45,
    "MJ_PRO_1M": 85,
    "MJ_MEGA_1M": 160,

    # Gemini
    "GEMINI_PLUS_1M": 18,
    "GEMINI_PRO_1M": 30,
    "GEMINI_ULTRA_1M": 290,

    # 历史兼容
    "GPT_ACTIVATE_3M": 69,
    "GPT_PLUS_3M": 69,
    "CLAUDE_ACTIVATE_3M": 69,
    "CLAUDE_PRO_3M": 78,
    "GEMINI_PRO_OLD_1M": 14,
    "PERPLEXITY_PRO_1M": 17,
    "CURSOR_PRO_1M": 21,
    "AI_BUNDLE_1M": 42,
    "GPT": 26,
    "VIP": 26,
    "CLAUDE": 26,
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
    amount_usd = product_amount_usd(product_code, PRICE_MAP_USD.get(product_code, 26))

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
        "amount_usdt_estimated": amount_usd,
        "raw": invoice,
    }


@router.post("/mock-checkout")
def legacy_mock_checkout(payload: CheckoutRequest, db: Session = Depends(get_db)):
    return nowpayments_checkout(payload=payload, db=db)
