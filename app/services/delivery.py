from datetime import datetime
from sqlalchemy.orm import Session

from app.models.entities import (
    Order,
    DeliveryRecord,
    MembershipEntitlement,
    InventoryItem,
)
from app.services.email_service import send_delivery_email


def get_inventory_code(db: Session, product_code: str):
    item = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.product_code == product_code,
            InventoryItem.is_used == 0,
        )
        .first()
    )

    if not item:
        raise Exception("库存不足")

    return item


def deliver_order(db: Session, order: Order):
    if not order:
        raise ValueError("order not found")

    # 避免重复发货
    existing = db.query(MembershipEntitlement).filter_by(order_id=order.id).first()
    if existing:
        return {
            "message": "already delivered",
            "content": existing.entitlement_code or existing.activation_result,
            "email_sent": False,
            "email_error": "订单已发货，本次未重复发送邮件",
        }

    # 1. 获取库存
    item = get_inventory_code(db, order.product_code)

    # 2. 标记库存已使用
    item.is_used = 1
    item.used_at = datetime.utcnow()
    item.order_id = order.id

    # 3. 发货内容
    content = item.code

    # 4. 更新订单
    order.delivery_status = "delivered"
    order.status = "completed"
    order.delivery_content = content

    # 5. 发货记录
    record = DeliveryRecord(
        order_id=order.id,
        status="success",
        content=content,
        created_at=datetime.utcnow(),
    )
    db.add(record)

    # 6. 权益记录
    entitlement = MembershipEntitlement(
        order_id=order.id,
        entitlement_code=content,
        activation_result="activated",
    )
    db.add(entitlement)

    db.commit()
    db.refresh(order)

    # 7. 发送邮件
    email_sent = False
    email_error = None
    email_result = None

    if order.customer_email:
        try:
            email_result = send_delivery_email(
                target_email=order.customer_email,
                product_code=order.product_code,
                order_no=order.order_no,
                delivery_content=content,
            )
            email_sent = True
            print(f"EMAIL SENT OK: order_no={order.order_no}, to={order.customer_email}")
        except Exception as e:
            email_error = str(e)
            print(f"EMAIL SEND ERROR: order_no={order.order_no}, to={order.customer_email}, error={repr(e)}")
    else:
        email_error = "订单没有 customer_email"
        print(f"EMAIL SEND SKIPPED: order_no={order.order_no}, reason=no customer_email")

    return {
        "message": "delivered",
        "content": content,
        "email_sent": email_sent,
        "email_error": email_error,
        "email_result": email_result,
    }


def mark_paid_and_deliver(db: Session, order: Order):
    if not order:
        raise ValueError("order not found")

    order.payment_status = "paid"
    order.status = "paid"

    db.commit()
    db.refresh(order)

    return deliver_order(db, order)
