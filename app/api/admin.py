from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.models.entities import Order
from app.core.admin_auth import get_current_admin

router = APIRouter()


# =========================
# 获取订单列表（必须有）
# =========================
@router.get("/admin/orders")
def get_orders(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    orders = db.query(Order).order_by(Order.created_at.desc()).all()
    return orders


# =========================
# 批量确认收款
# =========================
@router.post("/admin/orders/batch_pay")
def batch_pay_orders(
    order_ids: list[str] = Body(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    updated = []
    failed = []

    for order_id in order_ids:
        order = db.query(Order).filter(Order.order_no == order_id).first()

        if not order:
            failed.append({"order_no": order_id, "reason": "订单不存在"})
            continue

        if order.payment_status == "paid":
            failed.append({"order_no": order_id, "reason": "已支付"})
            continue

        try:
            order.payment_status = "paid"
            order.status = "completed"
            order.delivery_status = "delivered"

            # ⚠️ 如果你有发货函数，在这里调用
            # deliver_order(order)

            updated.append(order_id)

        except Exception as e:
            failed.append({"order_no": order_id, "reason": str(e)})

    db.commit()

    return {
        "success": updated,
        "failed": failed
    }
