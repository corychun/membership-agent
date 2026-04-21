from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy.orm import Session

from app.models.entities import Order, DeliveryRecord, MembershipEntitlement


def deliver_order(db: Session, order: Order):
    # ✅ 幂等：已发货直接返回
    existing = db.query(MembershipEntitlement).filter_by(order_id=order.id).first()
    if existing:
        return {
            "delivered": True,
            "idempotent": True,
            "content": existing.activation_result
        }

    # 模拟商品时长
    duration_days = 30
    expires_at = datetime.utcnow() + timedelta(days=duration_days)

    code = f"ENT-{uuid4().hex[:8].upper()}"

    result = f"Activation success | order={order.order_no} | code={code}"

    entitlement = MembershipEntitlement(
        order_id=order.id,
        product_code=order.product_code,
        entitlement_code=code,
        activation_result=result,
        expires_at=expires_at
    )

    record = DeliveryRecord(
        order_id=order.id,
        status="delivered",
        content=result,
        delivered_at=datetime.utcnow()
    )

    order.delivery_status = "delivered"
    order.delivery_content = result

    db.add(entitlement)
    db.add(record)
    db.add(order)

    db.commit()

    return {
        "delivered": True,
        "idempotent": False,
        "content": result
    }


def mark_paid_and_deliver(db: Session, order: Order):
    order.payment_status = "finished"
    order.status = "completed"
    order.paid_at = datetime.utcnow()

    db.add(order)
    db.commit()
    db.refresh(order)

    return deliver_order(db, order)