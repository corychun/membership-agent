from datetime import datetime
from typing import Any, Dict

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models.entities import DeliveryRecord, Order
from app.services.email_service import send_delivery_email


def _get_inventory_table(db: Session) -> Dict[str, Any]:
    inspector = inspect(db.bind)
    tables = inspector.get_table_names()

    table_name = None
    for name in ["inventory", "inventory_items", "inventory_item"]:
        if name in tables:
            table_name = name
            break

    if not table_name:
        raise Exception("库存表不存在，请先创建 inventory 或 inventory_items 表")

    cols = {c["name"] for c in inspector.get_columns(table_name)}

    product_col = "product_code" if "product_code" in cols else "product"
    content_col = "item_value" if "item_value" in cols else "content"

    if product_col not in cols:
        raise Exception("库存表缺少 product_code 或 product 字段")

    if content_col not in cols:
        raise Exception("库存表缺少 item_value 或 content 字段")

    return {
        "table": table_name,
        "cols": cols,
        "product_col": product_col,
        "content_col": content_col,
        "status_col": "status" if "status" in cols else None,
        "used_col": "is_used" if "is_used" in cols else None,
    }


def _available_where(meta: Dict[str, Any]) -> str:
    parts = []

    if meta["status_col"]:
        parts.append("LOWER(COALESCE(status, 'available')) IN ('available', 'new', 'unused')")

    if meta["used_col"]:
        parts.append("(is_used = false OR is_used IS NULL)")

    if not parts:
        return "1=1"

    return "(" + " OR ".join(parts) + ")"


def _get_available_inventory_item(db: Session, product_code: str):
    meta = _get_inventory_table(db)

    table = meta["table"]
    product_col = meta["product_col"]
    content_col = meta["content_col"]
    available_where = _available_where(meta)

    sql = text(f"""
        SELECT id, {content_col} AS content
        FROM {table}
        WHERE UPPER({product_col}) = :product_code
          AND {available_where}
        ORDER BY id ASC
        LIMIT 1
    """)

    return db.execute(sql, {"product_code": product_code.upper()}).mappings().first()


def _mark_inventory_used(db: Session, item_id: int, order: Order):
    meta = _get_inventory_table(db)

    table = meta["table"]
    cols = meta["cols"]

    updates = []

    if "status" in cols:
        updates.append("status = 'used'")

    if "is_used" in cols:
        updates.append("is_used = true")

    if "assigned_order_id" in cols:
        updates.append("assigned_order_id = :order_id")

    if "assigned_at" in cols:
        updates.append("assigned_at = :now")

    if "used_at" in cols:
        updates.append("used_at = :now")

    if not updates:
        return

    sql = text(f"""
        UPDATE {table}
        SET {", ".join(updates)}
        WHERE id = :item_id
    """)

    db.execute(sql, {
        "item_id": item_id,
        "order_id": str(order.id),
        "now": datetime.utcnow(),
    })


def _create_delivery_record_safe(db: Session, order: Order, content: str):
    """
    兼容你当前 DeliveryRecord 模型：
    只给模型支持的字段赋值，避免 delivered_at/status 这类字段不存在时报错。
    """
    mapper_cols = DeliveryRecord.__mapper__.columns.keys()

    kwargs = {}

    if "order_id" in mapper_cols:
        kwargs["order_id"] = order.id

    if "status" in mapper_cols:
        kwargs["status"] = "delivered"

    if "content" in mapper_cols:
        kwargs["content"] = content

    if "delivery_content" in mapper_cols:
        kwargs["delivery_content"] = content

    if "item_value" in mapper_cols:
        kwargs["item_value"] = content

    if "delivered_at" in mapper_cols:
        kwargs["delivered_at"] = datetime.utcnow()

    if "created_at" in mapper_cols:
        kwargs["created_at"] = datetime.utcnow()

    if kwargs:
        record = DeliveryRecord(**kwargs)
        db.add(record)


def deliver_order(db: Session, order: Order):
    if not order:
        raise ValueError("order not found")

    if str(order.delivery_status or "").lower() in {"delivered", "completed", "sent"}:
        return {
            "delivered": True,
            "idempotent": True,
            "content": order.delivery_content,
            "email_sent": False,
            "message": "already delivered",
        }

    item = _get_available_inventory_item(db, order.product_code)

    if not item:
        raise Exception(f"{order.product_code} 库存不足，请先在后台添加库存")

    content = item["content"]

    _mark_inventory_used(db, item["id"], order)

    order.delivery_status = "delivered"
    order.delivery_content = content
    order.status = "completed"

    _create_delivery_record_safe(db, order, content)

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
                delivery_content=content,
            )
            email_sent = True
        except Exception as e:
            email_error = str(e)

    return {
        "delivered": True,
        "idempotent": False,
        "content": content,
        "email_sent": email_sent,
        "email_result": email_result,
        "email_error": email_error,
    }


def mark_paid_and_deliver(db: Session, order: Order):
    if not order:
        raise ValueError("order not found")

    order.payment_status = "paid"
    order.status = "paid"

    if hasattr(order, "paid_at"):
        order.paid_at = datetime.utcnow()

    db.add(order)
    db.commit()
    db.refresh(order)

    return deliver_order(db, order)
