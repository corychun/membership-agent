from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.entities import Order
from app.core.admin_auth import get_current_admin

router = APIRouter()


# =============================
# 批量确认收款并发货
# =============================
@router.post("/admin/orders/batch_pay")
def batch_pay_orders(order_ids: list[str], db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    updated = []
    failed = []

    for order_id in order_ids:
        order = db.query(Order).filter(Order.order_no == order_id).first()

        if not order:
            failed.append({"order_no": order_id, "reason": "订单不存在"})
            continue

        if order.status == "completed":
            failed.append({"order_no": order_id, "reason": "已处理"})
            continue

        try:
            order.status = "completed"
            order.payment_status = "paid"
            order.delivery_status = "delivered"

            # 👉 这里调用你已有的发货逻辑
            # deliver_order(order)

            updated.append(order_id)

        except Exception as e:
            failed.append({"order_no": order_id, "reason": str(e)})

    db.commit()

    return {
        "success": updated,
        "failed": failed
    }
