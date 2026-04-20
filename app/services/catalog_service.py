from sqlalchemy.orm import Session
from app.models.entities import Product

DEFAULT_PRODUCTS = [
    {
        "code": "basic_plan",
        "provider": "openai",
        "official_plan_name": "Basic",
        "billing_cycle": "monthly",
        "official_price": 10.0,
        "currency": "USD",
        "service_fee": 1.0,
        "deliver_method": "api",
    }
]


def seed_products(db: Session) -> None:
    for item in DEFAULT_PRODUCTS:
        exists = db.query(Product).filter(Product.code == item["code"]).first()
        if not exists:
            db.add(Product(**item))
    db.commit()
