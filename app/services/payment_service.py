from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Delivery, Order, Payment


def create_mock_checkout(db: Session, order: Order) -> dict:
    payment = Payment(
        order_id=str(order.id),
        gateway="mock",
        gateway_payment_id=f"mock_{order.id}",
        checkout_url=f"https://mock-pay.local/checkout/{order.id}",
        amount=order.amount,
        currency=order.currency,
        status="pending",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return {
        "payment_id": str(payment.id),
        "checkout_url": payment.checkout_url,
        "status": payment.status,
    }


def mark_payment_status(db: Session, order: Order, status: str) -> Order:
    order.payment_status = status
    if status == "paid":
        order.status = "paid"
        if order.review_status == "not_required":
            order.delivery_status = "queued"
    db.add(order)
    payment = db.query(Payment).filter(Payment.order_id == str(order.id)).order_by(Payment.created_at.desc()).first()
    if payment:
        payment.status = status
        db.add(payment)
    db.commit()
    db.refresh(order)
    return order


def get_latest_usdt_payment(db: Session, order_id: str) -> Payment | None:
    return (
        db.query(Payment)
        .filter(Payment.order_id == order_id, Payment.payment_method == "usdt")
        .order_by(Payment.created_at.desc())
        .first()
    )


def serialize_usdt_payment(payment: Payment) -> dict:
    return {
        "order_id": payment.order_id,
        "payment_method": payment.payment_method or "usdt",
        "network": payment.network or "TRC20",
        "wallet_address": payment.wallet_address,
        "amount_usdt": float(payment.amount_usdt or 0),
        "status": payment.status,
        "tx_hash": payment.tx_hash,
        "confirmed_at": payment.confirmed_at.isoformat() if payment.confirmed_at else None,
    }


def create_usdt_payment(db: Session, order: Order) -> dict:
    payment = get_latest_usdt_payment(db, str(order.id))
    if payment is None:
        payment = Payment(
            order_id=str(order.id),
            gateway="usdt_trc20",
            gateway_payment_id=f"usdt_{order.id}",
            amount=order.amount,
            currency=order.currency,
            payment_method="usdt",
            network="TRC20",
            wallet_address=settings.usdt_trc20_address,
            amount_usdt=order.amount,
            status="pending",
        )
        db.add(payment)
    else:
        payment.gateway = "usdt_trc20"
        payment.gateway_payment_id = f"usdt_{order.id}"
        payment.payment_method = "usdt"
        payment.network = "TRC20"
        payment.wallet_address = settings.usdt_trc20_address
        payment.amount_usdt = order.amount
        if payment.status != "paid":
            payment.status = "pending"
        db.add(payment)

    db.commit()
    db.refresh(payment)
    return serialize_usdt_payment(payment)


def confirm_usdt_payment(db: Session, order: Order, tx_hash: str) -> dict:
    payment = get_latest_usdt_payment(db, str(order.id))
    if payment is None:
        raise ValueError("USDT payment not found")

    payment.status = "paid"
    payment.tx_hash = tx_hash
    payment.confirmed_at = datetime.utcnow()
    payment.payment_method = "usdt"
    payment.network = "TRC20"
    payment.wallet_address = settings.usdt_trc20_address
    payment.amount_usdt = order.amount
    db.add(payment)

    order.payment_status = "paid"
    order.status = "paid"
    if order.review_status == "not_required":
        order.delivery_status = "queued"
        delivery = (
            db.query(Delivery)
            .filter(Delivery.order_id == str(order.id))
            .order_by(Delivery.created_at.desc())
            .first()
        )
        if delivery is None:
            db.add(
                Delivery(
                    order_id=str(order.id),
                    delivery_type="manual_invite",
                    target_email=order.target_email,
                    delivery_status="queued",
                )
            )
    db.add(order)

    db.commit()
    db.refresh(order)
    db.refresh(payment)

    return {
        **serialize_usdt_payment(payment),
        "payment_status": order.payment_status,
        "delivery_status": order.delivery_status,
        "review_status": order.review_status,
        "status": order.status,
    }
