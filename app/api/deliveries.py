from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order
from app.services.delivery import deliver_order
from app.services.email_service import send_delivery_email

router = APIRouter(tags=["deliveries"])


class TriggerDeliveryRequest(BaseModel):
    order_no: str


class TestEmailRequest(BaseModel):
    to_email: EmailStr
    order_no: str = "TEST-ORDER"
    product_code: str = "test_product"
    delivery_content: str = "Activation success | order=TEST-ORDER | code=ENT-TEST1234"


@router.post("/deliveries/trigger")
def trigger(payload: TriggerDeliveryRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter_by(order_no=payload.order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="order not found")

    return deliver_order(db, order)


@router.post("/deliveries/test-email")
def test_email(payload: TestEmailRequest):
    result = send_delivery_email(
        target_email=payload.to_email,
        product_code=payload.product_code,
        order_no=payload.order_no,
        delivery_content=payload.delivery_content,
    )
    return {
        "ok": True,
        "message": "test email sent",
        "result": result,
    }
