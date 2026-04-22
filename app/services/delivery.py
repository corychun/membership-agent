from sqlalchemy.orm import Session
from app.models.entities import Order, DeliveryRecord, MembershipEntitlement, InventoryItem
from datetime import datetime


def get_inventory_code(db: Session, product_code: str):
    item = db.query(InventoryItem)\
        .filter(InventoryItem.product_code == product_code, InventoryItem.is_used == 0)\
        .first()

    if not item:
        raise Exception("库存不足")

    return item


def deliver_order(db: Session, order: Order):
    # 1️⃣ 获取库存
    item = get_inventory_code(db, order.product_code)

    # 2️⃣ 标记库存已使用
    item.is_used = 1
    item.used_at = datetime.utcnow()
    item.order_id = order.id

    # 3️⃣ 发货内容
    content = item.code

    # 4️⃣ 更新订单
    order.delivery_status = "delivered"
    order.status = "completed"
    order.delivery_content = content

    # 5️⃣ 发货记录
    record = DeliveryRecord(
        order_id=order.id,
        status="success",
        content=content,
        created_at=datetime.utcnow()
    )
    db.add(record)

    # 6️⃣ 权益记录
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
    order.payment_status = "paid"
    order.status = "paid"

    db.commit()

    return deliver_order(db, order)
