from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order
from app.services.delivery_service import complete_delivery

router = APIRouter(prefix="/deliveries", tags=["deliveries"])


@router.post("/{order_id}/complete")
def mark_delivery_complete(order_id: UUID, note: str | None = None, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    updated = complete_delivery(db, order, note=note)
    return {
        "order_id": str(updated.id),
        "status": updated.status,
        "delivery_status": updated.delivery_status,
    }
