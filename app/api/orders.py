from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from uuid import uuid4

from app.core.db import get_db
from app.models.entities import Order

router = APIRouter()


@router.post("/orders")
def create_order(data: dict, db: Session = Depends(get_db)):
    order = Order(
        order_no=f"ORD-{uuid4().hex[:8].upper()}",
        product_code=data.get("product_code"),
        customer_email=data.get("customer_email"),
        amount_usd=9.9,
        currency="USD"
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    return order


@router.get("/orders/{order_no}")
def get_order(order_no: str, db: Session = Depends(get_db)):
    return db.query(Order).filter_by(order_no=order_no).first()
