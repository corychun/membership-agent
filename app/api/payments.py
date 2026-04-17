from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order
from app.schemas.payment import CreateUsdtPaymentRequest, MockCheckoutRequest
from app.services.payment_service import create_mock_checkout, create_usdt_payment, get_latest_usdt_payment, serialize_usdt_payment

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/mock-checkout")
def mock_checkout(payload: MockCheckoutRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == payload.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return create_mock_checkout(db, order)


@router.post("/usdt/create")
def create_usdt_checkout(payload: CreateUsdtPaymentRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == payload.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return create_usdt_payment(db, order)


@router.get("/usdt/{order_id}")
def get_usdt_payment(order_id: str, db: Session = Depends(get_db)):
    payment = get_latest_usdt_payment(db, order_id)
    if not payment:
        raise HTTPException(status_code=404, detail="USDT payment not found")

    return serialize_usdt_payment(payment)
