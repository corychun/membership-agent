from uuid import uuid4
from sqlalchemy.orm import Session

from app.models.entities import Order, DeliveryRecord, MembershipEntitlement


def deliver_order(db: Session, order: Order):
    existing = db.query(MembershipEntitlement).filter_by(order_id=order.id).first()
    if existing:
        return {"msg": "already delivered"}

    code = f"ENT-{uuid4().hex[:8].upper()}"
    result = f"Activation success | order={order.order_no} | code={code}"

    entitlement = MembershipEntitlement(
        order_id=order.id,
        entitlement_code=code,
        activation_result=result,
    )

    record = DeliveryRecord(
        order_id=order.id,
        status="delivered",
        content=result,
    )

    order.delivery_status = "delivered"
    order.delivery_content = result

    db.add(entitlement)
    db.add(record)
    db.add(order)

    db.commit()

    return {"msg": "delivered", "code": code}


def mark_paid_and_deliver(db: Session, order: Order):
    order.payment_status = "finished"
    order.status = "completed"

    db.add(order)
    db.commit()
    db.refresh(order)

    return deliver_order(db, order)
