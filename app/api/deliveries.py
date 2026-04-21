from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order
from app.services.delivery import deliver_order

router = APIRouter()


@router.post("/deliveries/trigger")
def trigger(data: dict, db: Session = Depends(get_db)):
    order = db.query(Order).filter_by(order_no=data["order_no"]).first()
    return deliver_order(db, order)
