from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.db import get_db
from app.models.entities import Order
from app.services.delivery import deliver_order

router = APIRouter(tags=["deliveries"])


class TriggerDeliveryRequest(BaseModel):
    order_no: str


@router.post("/deliveries/trigger")
def trigger(payload: TriggerDeliveryRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter_by(order_no=payload.order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="order not found")

    return deliver_order(db, order)
