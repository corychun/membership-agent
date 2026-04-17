from datetime import datetime
from sqlalchemy.orm import Session
from app.models.entities import Delivery, Order


def create_delivery_task(db: Session, order: Order, delivery_type: str) -> Delivery:
    delivery = Delivery(
        order_id=str(order.id),
        delivery_type=delivery_type,
        target_email=order.target_email,
        delivery_status="queued",
    )
    db.add(delivery)
    order.delivery_status = "queued"
    db.add(order)
    db.commit()
    db.refresh(delivery)
    return delivery


def complete_delivery(db: Session, order: Order, note: str | None = None) -> Order:
    delivery = db.query(Delivery).filter(Delivery.order_id == str(order.id)).order_by(Delivery.created_at.desc()).first()
    if delivery:
        delivery.delivery_status = "completed"
        delivery.delivery_notes = note
        delivery.delivered_at = datetime.utcnow()
        db.add(delivery)

    order.delivery_status = "completed"
    order.status = "fulfilled"
    db.add(order)
    db.commit()
    db.refresh(order)
    return order
