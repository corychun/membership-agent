from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
import os
import uuid
from app.core.db import get_db
from app.models.entities import Order, InventoryItem

router = APIRouter(prefix="/admin", tags=["admin"])


def check_admin_password(password: str):
    if password != os.getenv("ADMIN_PASSWORD", "123456"):
        raise HTTPException(status_code=401, detail="Invalid admin password")


# =========================
# 订单列表
# =========================
@router.get("/orders")
def list_orders(admin_password: str = Query(...), db: Session = Depends(get_db)):
    check_admin_password(admin_password)

    orders = db.query(Order).all()

    return {
        "items": [
            {
                "order_id": o.order_id,
                "email": o.email,
                "product_code": o.product_code,
                "amount": o.amount,
                "status": o.status,
                "payment_status": o.payment_status,
                "delivery_status": o.delivery_status,
                "created_at": str(o.created_at),
            }
            for o in orders
        ]
    }


# =========================
# 添加库存
# =========================
@router.post("/inventory")
def add_inventory(data: dict, db: Session = Depends(get_db)):
    check_admin_password(data.get("admin_password"))

    item = InventoryItem(
        product_code=data["product_code"],
        item_type=data["item_type"],
        item_value=data["item_value"],
        item_secret=data.get("item_secret"),
        status="available",
    )

    db.add(item)
    db.commit()

    return {"ok": True}


# =========================
# 查询库存
# =========================
@router.get("/inventory")
def get_inventory(admin_password: str = Query(...), db: Session = Depends(get_db)):
    check_admin_password(admin_password)

    items = db.query(InventoryItem).all()

    return {
        "items": [
            {
                "id": i.id,
                "product_code": i.product_code,
                "item_value": i.item_value,
                "status": i.status,
            }
            for i in items
        ]
    }


# =========================
# 自动发货
# =========================


import uuid
from fastapi import HTTPException

@router.post("/fulfillment/run")
def run_fulfillment(data: dict, db: Session = Depends(get_db)):
    # ✅ 管理员校验
    check_admin_password(data.get("admin_password"))

    # ✅ 查订单
    order = db.query(Order).filter(
        Order.id == uuid.UUID(data["order_id"])
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.payment_status != "paid":
        raise HTTPException(status_code=400, detail="Order not paid")

    # ✅ 找库存
    item = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.product_code == order.product_code,
            InventoryItem.status == "available",
        )
        .first()
    )

    if not item:
        raise HTTPException(status_code=400, detail="No inventory available")

    # ✅ 发货
    item.status = "assigned"
    item.assigned_order_id = str(order.id)

    order.status = "fulfilled"
    order.delivery_status = "completed"

    db.commit()

    return {
        "ok": True,
        "order_id": str(order.id),
        "item_value": item.item_value,
    }