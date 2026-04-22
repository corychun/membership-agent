from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.models.entities import InventoryItem

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.post("/add")
def add_inventory(product_code: str, code: str, db: Session = Depends(get_db)):
    item = InventoryItem(
        product_code=product_code,
        code=code
    )
    db.add(item)
    db.commit()
    return {"msg": "added"}


@router.get("/list")
def list_inventory(product_code: str, db: Session = Depends(get_db)):
    items = db.query(InventoryItem)\
        .filter(InventoryItem.product_code == product_code)\
        .all()

    return items


@router.get("/available")
def available_inventory(product_code: str, db: Session = Depends(get_db)):
    count = db.query(InventoryItem)\
        .filter(InventoryItem.product_code == product_code, InventoryItem.is_used == 0)\
        .count()

    return {"available": count}