from fastapi import APIRouter, Depends, Request, Header, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import hmac
import hashlib
import json
import os

from app.core.db import get_db
from app.models.entities import Order
from app.services.delivery import mark_paid_and_deliver

router = APIRouter()


# =============================
# ✅ mock-payment（保留测试）
# =============================
class MockPaymentRequest(BaseModel):
    order_no: str


@router.post("/webhooks/mock-payment")
def mock_payment(payload: MockPaymentRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter_by(order_no=payload.order_no).first()

    if not order:
        return {"error": "order not found"}

    result = mark_paid_and_deliver(db, order)

    return {
        "msg": "paid + delivered",
        "result": result
    }


# =============================
# ✅ NOWPayments 签名校验
# =============================
def verify_nowpayments_signature(payload: bytes, signature: str):
    secret = os.getenv("NOWPAYMENTS_IPN_SECRET")
    if not secret:
        raise Exception("NOWPAYMENTS_IPN_SECRET not set")

    generated = hmac.new(
        key=secret.encode(),
        msg=payload,
        digestmod=hashlib.sha512
    ).hexdigest()

    return hmac.compare_digest(generated, signature)


# =============================
# ✅ 真实 webhook（核心）
# =============================
@router.post("/webhooks/nowpayments")
async def nowpayments_webhook(
    request: Request,
    x_nowpayments_sig: str = Header(None),
    db: Session = Depends(get_db)
):
    raw_body = await request.body()

    # 1️⃣ 校验签名
    if not verify_nowpayments_signature(raw_body, x_nowpayments_sig):
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(raw_body)

    payment_status = data.get("payment_status")
    order_no = data.get("order_id")  # 你创建 invoice 时传的 order_id

    order = db.query(Order).filter_by(order_no=order_no).first()

    if not order:
        return {"msg": "order not found"}

    # 2️⃣ 支付成功 → 自动发货
    if payment_status in ["finished", "confirmed"]:
        result = mark_paid_and_deliver(db, order)

        return {
            "msg": "payment success + delivered",
            "result": result
        }

    # 3️⃣ 其他状态（更新但不发货）
    elif payment_status in ["waiting", "pending"]:
        order.payment_status = "waiting"
    elif payment_status in ["failed", "expired"]:
        order.payment_status = "failed"

    db.add(order)
    db.commit()

    return {"msg": "status updated", "payment_status": payment_status}
