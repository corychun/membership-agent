from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order
from app.services.delivery import mark_paid_and_deliver

router = APIRouter()


@router.post("/webhooks/mock-payment")
def mock_payment(data: dict, db: Session = Depends(get_db)):
    order = db.query(Order).filter_by(order_no=data["order_no"]).first()

    if not order:
        return {"error": "order not found"}

    result = mark_paid_and_deliver(db, order)

    return {
        "msg": "paid + delivered",
        "result": result
    }
