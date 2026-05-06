from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services.product_config_service import list_products_for_public

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/public")
def public_products(db: Session = Depends(get_db)):
    return {"ok": True, "items": list_products_for_public(db)}
