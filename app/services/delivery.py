from sqlalchemy.orm import Session
from app.models.entities import Order, DeliveryRecord, MembershipEntitlement
from datetime import datetime


def deliver_order(db: Session, order: Order):
    # 1️⃣ 标记订单已发货
    order.delivery_status = "delivered"
    order.status = "completed"

    # 2️⃣ 生成发货内容（你可以以后改成真实卡密）
    content = f"VIP-CODE-{order.order_no}"

    order.delivery_content = content

    # 3️⃣ 写入发货记录
    record = DeliveryRecord(
        order_id=order.id,
        status="success",
        content=content,
        created_at=datetime.utcnow()
    )
    db.add(record)

    # 4️⃣ 写入会员权益（⚠️ 修复点在这里）
    entitlement = MembershipEntitlement(
        order_id=order.id,
        entitlement_code=content,
        activation_result="activated"
    )
    db.add(entitlement)

    db.commit()

    return {
        "message": "delivered",
        "content": content
    }


def mark_paid_and_deliver(db: Session, order: Order):
    # 标记支付成功
    order.payment_status = "paid"
    order.status = "paid"

    db.commit()

    # 发货
    return deliver_order(db, order)
