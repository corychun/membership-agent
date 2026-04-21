from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.models.order import Order

router = APIRouter()


# =========================
# NOWPayments Webhook（真实回调）
# =========================
@router.post("/webhooks/nowpayments")
async def nowpayments_webhook(request: Request, db: Session = Depends(get_db)):
    data = await request.json()

    payment_status = data.get("payment_status")
    order_id = data.get("order_id")

    if not order_id:
        return {"error": "missing order_id"}

    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        return {"error": "order not found"}

    # 根据支付状态更新
    if payment_status in ["finished", "confirmed"]:
        order.payment_status = "finished"
        order.status = "completed"

    elif payment_status in ["failed", "expired"]:
        order.payment_status = "failed"
        order.status = "failed"

    else:
        order.payment_status = "waiting"

    db.commit()

    return {"message": "ok"}


# =========================
# Mock 支付（测试用，一键成功）
# =========================
@router.post("/webhooks/mock-payment")
def mock_payment(db: Session = Depends(get_db)):
    # 取最新一条订单
    order = db.query(Order).order_by(Order.created_at.desc()).first()

    if not order:
        return {"error": "no order found"}

    order.payment_status = "finished"
    order.status = "completed"

    db.commit()

    return {
        "message": "mock payment success",
        "order_id": str(order.id)
    }
