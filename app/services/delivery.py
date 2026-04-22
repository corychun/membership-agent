from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.entities import DeliveryRecord, MembershipEntitlement, Order
from app.services.email_service import send_delivery_email


def deliver_order(db: Session, order: Order):
    if not order:
        raise ValueError("order not found")

    existing = db.query(MembershipEntitlement).filter_by(order_id=order.id).first()
    if existing:
        return {
            "delivered": True,
            "idempotent": True,
            "content": existing.activation_result,
            "email_sent": False,
            "message": "already delivered",
        }

    duration_days = 30
    expires_at = datetime.utcnow() + timedelta(days=duration_days)

    code = f"ENT-{uuid4().hex[:8].upper()}"
    result = f"Activation success | order={order.order_no} | code={code}"

    entitlement = MembershipEntitlement(
        order_id=order.id,
        entitlement_code=code,
        activation_result=result,
        expires_at=expires_at,
    )

    record = DeliveryRecord(
        order_id=order.id,
        status="delivered",
        content=result,
        delivered_at=datetime.utcnow(),
    )

    order.delivery_status = "delivered"
    order.delivery_content = result

    db.add(entitlement)
    db.add(record)
    db.add(order)
    db.commit()
    db.refresh(order)

    email_result = None
    email_sent = False
    email_error = None

    if order.customer_email:
        try:
            email_result = send_delivery_email(
                target_email=order.customer_email,
                product_code=order.product_code,
                order_no=order.order_no,
                delivery_content=result,
            )
            email_sent = True
        except Exception as e:
            email_error = str(e)

    return {
        "delivered": True,
        "idempotent": False,
        "content": result,
        "email_sent": email_sent,
        "email_result": email_result,
        "email_error": email_error,
    }


def mark_paid_and_deliver(db: Session, order: Order):
    if not order:
        raise ValueError("order not found")

    order.payment_status = "finished"
    order.status = "completed"
    order.paid_at = datetime.utcnow()

    db.add(order)
    db.commit()
    db.refresh(order)

    return deliver_order(db, order)
