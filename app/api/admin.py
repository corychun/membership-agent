import os
import smtplib
import ssl
import uuid
from datetime import datetime
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order, InventoryItem, Delivery

router = APIRouter(prefix="/admin", tags=["admin"])


class ConfirmPaidRequest(BaseModel):
    admin_password: str
    order_id: str


class AddInventoryRequest(BaseModel):
    admin_password: str
    product_code: str
    item_value: str
    item_type: str = "redeem_code"
    item_secret: str | None = None


def check_admin_password(password: str | None):
    if password != os.getenv("ADMIN_PASSWORD", "123456"):
        raise HTTPException(status_code=401, detail="Invalid admin password")


def _send_delivery_email(to_email: str, product_code: str, order_id: str, content: str) -> dict:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from_email = os.getenv("SMTP_FROM_EMAIL", smtp_username).strip()
    smtp_from_name = os.getenv("SMTP_FROM_NAME", "Membership Agent").strip()
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}

    if not smtp_host or not smtp_username or not smtp_password or not smtp_from_email:
        return {
            "ok": False,
            "error": "SMTP not configured",
        }

    msg = EmailMessage()
    msg["Subject"] = f"Your delivery for {product_code}"
    msg["From"] = f"{smtp_from_name} <{smtp_from_email}>"
    msg["To"] = to_email

    body = f"""Your order has been delivered successfully

Order ID: {order_id}
Product: {product_code}

Delivery result:
{content}

Thank you.
"""
    msg.set_content(body)

    try:
      if smtp_use_tls:
          context = ssl.create_default_context()
          with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
              server.starttls(context=context)
              server.login(smtp_username, smtp_password)
              server.send_message(msg)
      else:
          with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as server:
              server.login(smtp_username, smtp_password)
              server.send_message(msg)

      return {"ok": True, "to": to_email, "subject": msg["Subject"]}
    except Exception as e:
      return {"ok": False, "error": str(e)}


def _deliver_order(db: Session, order: Order) -> dict:
    if order.delivery_status == "completed":
        item = (
            db.query(InventoryItem)
            .filter(InventoryItem.assigned_order_id == str(order.id))
            .first()
        )
        return {
            "message": "already delivered",
            "content": item.item_value if item else None,
            "email_sent": False,
            "email_error": "订单已发货，本次未重复发送邮件",
        }

    item = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.product_code == order.product_code,
            InventoryItem.status == "available",
        )
        .order_by(InventoryItem.id.asc())
        .first()
    )

    if not item:
        raise HTTPException(status_code=400, detail=f"No inventory available for {order.product_code}")

    now = datetime.utcnow()

    item.status = "assigned"
    item.assigned_order_id = str(order.id)
    item.assigned_at = now

    order.payment_status = "finished"
    order.status = "fulfilled"
    order.delivery_status = "completed"
    order.updated_at = now

    delivery = Delivery(
        order_id=str(order.id),
        delivery_type=item.item_type or "redeem_code",
        target_email=order.target_email or order.email,
        delivery_status="completed",
        delivery_notes=item.item_value,
        created_at=now,
        delivered_at=now,
    )

    db.add(item)
    db.add(order)
    db.add(delivery)
    db.commit()
    db.refresh(order)

    email_result = _send_delivery_email(
        to_email=order.target_email or order.email,
        product_code=order.product_code,
        order_id=str(order.id),
        content=item.item_value,
    )

    return {
        "message": "delivered",
        "content": item.item_value,
        "email_sent": email_result.get("ok", False),
        "email_error": email_result.get("error"),
        "email_result": email_result,
    }


@router.get("/orders")
def list_orders(admin_password: str = Query(...), db: Session = Depends(get_db)):
    check_admin_password(admin_password)

    orders = (
        db.query(Order)
        .order_by(Order.created_at.desc())
        .limit(100)
        .all()
    )

    return {
        "items": [
            {
                "order_id": str(o.id),
                "email": o.email,
                "target_email": o.target_email,
                "product_code": o.product_code,
                "amount": float(o.amount) if o.amount is not None else None,
                "currency": o.currency,
                "status": o.status,
                "payment_status": o.payment_status,
                "delivery_status": o.delivery_status,
                "review_status": o.review_status,
                "created_at": str(o.created_at) if o.created_at else None,
                "updated_at": str(o.updated_at) if o.updated_at else None,
            }
            for o in orders
        ]
    }


@router.post("/orders/confirm-paid")
def confirm_paid_and_deliver(payload: ConfirmPaidRequest, db: Session = Depends(get_db)):
    check_admin_password(payload.admin_password)

    try:
        order_uuid = uuid.UUID(payload.order_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order_id")

    order = db.query(Order).filter(Order.id == order_uuid).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    result = _deliver_order(db, order)

    return {
        "ok": True,
        "msg": "paid + delivered",
        "order_id": str(order.id),
        "result": result,
        "item_value": result.get("content"),
    }


@router.post("/inventory")
def add_inventory(payload: AddInventoryRequest, db: Session = Depends(get_db)):
    check_admin_password(payload.admin_password)

    item = InventoryItem(
        product_code=payload.product_code,
        item_type=payload.item_type,
        item_value=payload.item_value,
        item_secret=payload.item_secret,
        status="available",
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    return {
        "ok": True,
        "id": item.id,
        "product_code": item.product_code,
        "status": item.status,
    }


@router.get("/inventory")
def get_inventory(admin_password: str = Query(...), db: Session = Depends(get_db)):
    check_admin_password(admin_password)

    items = (
        db.query(InventoryItem)
        .order_by(InventoryItem.id.desc())
        .limit(200)
        .all()
    )

    return {
        "items": [
            {
                "id": i.id,
                "product_code": i.product_code,
                "item_type": i.item_type,
                "item_value": i.item_value,
                "status": i.status,
                "assigned_order_id": i.assigned_order_id,
                "assigned_at": str(i.assigned_at) if i.assigned_at else None,
                "created_at": str(i.created_at) if i.created_at else None,
            }
            for i in items
        ]
    }


@router.post("/fulfillment/run")
def run_fulfillment(data: dict, db: Session = Depends(get_db)):
    check_admin_password(data.get("admin_password"))

    order_id = data.get("order_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="order_id is required")

    try:
        order_uuid = uuid.UUID(order_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order_id")

    order = db.query(Order).filter(Order.id == order_uuid).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    result = _deliver_order(db, order)

    return {
        "ok": True,
        "order_id": str(order.id),
        "result": result,
        "item_value": result.get("content"),
    }
