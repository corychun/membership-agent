import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Product, Order, Audit
from app.schemas.order import CreateOrderRequest, CreateOrderResponse
from app.services.quote_service import build_quote
from app.services.risk_service import run_risk_check

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=CreateOrderResponse)
def create_order(payload: CreateOrderRequest, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.code == payload.product_code, Product.is_active.is_(True)).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    quote = build_quote(product, payload.seats)
    risk = run_risk_check(payload.email, payload.seats, quote["total"], ip="api")

    review_status = "required" if risk["needs_manual_review"] else "not_required"
    order = Order(
        email=payload.email,
        user_type=payload.user_type,
        product_code=payload.product_code,
        target_email=payload.target_email,
        seats=payload.seats,
        amount=quote["total"],
        currency=quote["currency"],
        review_status=review_status,
        delivery_status="pending",
        payment_status="unpaid",
        status="created",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    audit = Audit(
        order_id=str(order.id),
        risk_score=risk["risk_score"],
        flags_json=json.dumps(risk["flags"], ensure_ascii=False),
        decision="pending" if review_status == "required" else "auto_pass",
    )
    db.add(audit)
    db.commit()

    return CreateOrderResponse(
        order_id=str(order.id),
        status=order.status,
        payment_status=order.payment_status,
        review_status=order.review_status,
        delivery_status=order.delivery_status,
        amount=float(order.amount),
        currency=order.currency,
    )
