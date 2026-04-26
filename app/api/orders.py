from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.db import SessionLocal
from app.models.order import Order
from app.models.inventory import Inventory
import uuid
import datetime

router = APIRouter()

class CreateOrderRequest(BaseModel):
    product_code: str
    email: str


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/orders/create")
def create_order(data: CreateOrderRequest):
    db: Session = next(get_db())

    # 🔥 1. 检查库存（防超卖）
    available_items = db.query(Inventory).filter(
        Inventory.product_code == data.product_code,
        Inventory.is_used == False
    ).all()

    if len(available_items) <= 0:
        raise HTTPException(status_code=400, detail="库存不足")

    # 🔥 2. 创建订单
    order_no = "ORD-" + uuid.uuid4().hex[:8].upper()

    order = Order(
        order_no=order_no,
        product_code=data.product_code,
        customer_email=data.email,
        status="pending_payment",
        payment_status="pending",
        delivery_status="pending",
        created_at=datetime.datetime.utcnow()
    )

    db.add(order)
    db.commit()

    return {
        "order_no": order_no
    }
