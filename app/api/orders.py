import random
import string
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order

router = APIRouter(tags=["orders"])


class CreateOrderRequest(BaseModel):
    product_code: str
    customer_email: Optional[EmailStr] = None
    email: Optional[EmailStr] = None


def make_order_no() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"ORD-{suffix}"


def get_customer_email(data: CreateOrderRequest) -> str:
    email = data.customer_email or data.email
    if not email:
        raise HTTPException(status_code=400, detail="缺少邮箱")
    return str(email)


def get_inventory_meta(db: Session):
    inspector = inspect(db.bind)
    tables = inspector.get_table_names()

    table_name = None
    for name in ["inventory", "inventory_items", "inventory_item"]:
        if name in tables:
            table_name = name
            break

    if not table_name:
        raise HTTPException(status_code=500, detail="库存表不存在")

    cols = {c["name"] for c in inspector.get_columns(table_name)}

    product_col = "product_code" if "product_code" in cols else "product"

    if product_col not in cols:
        raise HTTPException(
            status_code=500,
            detail="库存表缺少 product_code 或 product 字段",
        )

    return {
        "table": table_name,
        "product_col": product_col,
        "status_col": "status" if "status" in cols else None,
        "used_col": "is_used" if "is_used" in cols else None,
    }


def available_where(meta) -> str:
    parts = []

    if meta["status_col"]:
        parts.append(
            "LOWER(COALESCE(status, 'available')) IN ('available', 'new', 'unused')"
        )

    if meta["used_col"]:
        parts.append("(is_used = false OR is_used IS NULL)")

    if not parts:
        return "1=1"

    return "(" + " OR ".join(parts) + ")"


def get_available_stock_count(db: Session, product_code: str) -> int:
    meta = get_inventory_meta(db)

    sql = text(f"""
        SELECT COUNT(*) AS count
        FROM {meta["table"]}
        WHERE UPPER({meta["product_col"]}) = :product_code
          AND {available_where(meta)}
    """)

    row = db.execute(sql, {"product_code": product_code.upper()}).mappings().first()
    return int(row["count"] or 0)


def create_order_logic(data: CreateOrderRequest, db: Session):
    product_code = data.product_code.upper().strip()
    customer_email = get_customer_email(data)

    stock_count = get_available_stock_count(db, product_code)

    if stock_count <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"{product_code} 库存不足，暂时无法购买",
        )

    order_no = make_order_no()

    order = Order(
        order_no=order_no,
        product_code=product_code,
        customer_email=customer_email,
        status="pending_payment",
        payment_status="pending",
        delivery_status="pending",
        delivery_content=None,
        created_at=datetime.utcnow(),
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    return {
        "id": order.id,
        "order_no": order.order_no,
        "product_code": order.product_code,
        "customer_email": order.customer_email,
        "status": order.status,
        "payment_status": order.payment_status,
        "delivery_status": order.delivery_status,
        "stock_available": stock_count,
    }


@router.post("/orders")
def create_order(data: CreateOrderRequest, db: Session = Depends(get_db)):
    return create_order_logic(data, db)


@router.post("/orders/create")
def create_order_legacy(data: CreateOrderRequest, db: Session = Depends(get_db)):
    return create_order_logic(data, db)


@router.get("/orders/{order_no}")
def get_order(order_no: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.order_no == order_no).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "id": order.id,
        "order_no": order.order_no,
        "product_code": order.product_code,
        "customer_email": order.customer_email,
        "status": order.status,
        "payment_status": order.payment_status,
        "delivery_status": order.delivery_status,
        "delivery_content": order.delivery_content,
        "created_at": str(order.created_at) if order.created_at else None,
    }
