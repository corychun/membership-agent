from sqlalchemy.orm import Session
from app.models.entities import Product

DEFAULT_PRODUCTS = [
    {
        "code": "chatgpt-business-monthly",
        "provider": "OpenAI",
        "official_plan_name": "ChatGPT Business",
        "billing_cycle": "monthly",
        "official_price": 25.0,
        "currency": "USD",
        "service_fee": 3.0,
        "deliver_method": "enterprise_seat",
    },
    {
        "code": "ai-tools-procurement-service",
        "provider": "Internal",
        "official_plan_name": "AI Tools Procurement Service",
        "billing_cycle": "monthly",
        "official_price": 20.0,
        "currency": "USD",
        "service_fee": 5.0,
        "deliver_method": "manual_invite",
    },
]


def seed_products(db: Session) -> None:
    for item in DEFAULT_PRODUCTS:
        exists = db.query(Product).filter(Product.code == item["code"]).first()
        if not exists:
            db.add(Product(**item))
    db.commit()
