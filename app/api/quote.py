from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Product
from app.schemas.quote import QuoteRequest, QuoteResponse
from app.services.quote_service import build_quote
from app.services.risk_service import run_risk_check

router = APIRouter(prefix="/quote", tags=["quote"])


@router.post("", response_model=QuoteResponse)
def create_quote(payload: QuoteRequest, request: Request, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.code == payload.product_code, Product.is_active.is_(True)).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    quote = build_quote(product, payload.seats)
    risk = run_risk_check(
        email=payload.email,
        seats=payload.seats,
        amount=quote["total"],
        ip=request.client.host if request.client else None,
    )
    return {**quote, **risk}
