from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order
from app.services.stripe_service import create_checkout_session

router = APIRouter(prefix="/stripe", tags=["stripe"])


@router.post("/checkout")
def stripe_checkout(data: dict, db: Session = Depends(get_db)):
    order_id = data.get("order_id")

    if not order_id:
        raise HTTPException(400, "order_id required")

    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        raise HTTPException(404, "Order not found")

    url = create_checkout_session(order)

    return {
        "checkout_url": url
    }