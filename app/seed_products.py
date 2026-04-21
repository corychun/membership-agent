from app.core.db import SessionLocal
from app.models.entities import Product


def seed_products():
    db = SessionLocal()
    try:
        existing = db.query(Product).filter(Product.code == "basic_plan").first()

        if existing:
            existing.provider = "openai"
            existing.official_plan_name = "Basic"
            existing.billing_cycle = "monthly"
            existing.official_price = 18
            existing.currency = "USD"
            existing.service_fee = 2
            existing.deliver_method = "api"
            existing.is_active = True

            db.commit()
            print("✅ basic_plan updated to total = 20 USD")
            return

        p = Product(
            code="basic_plan",
            provider="openai",
            official_plan_name="Basic",
            billing_cycle="monthly",
            official_price=18,
            currency="USD",
            service_fee=2,
            deliver_method="api",
            is_active=True
        )

        db.add(p)
        db.commit()
        print("✅ basic_plan created with total = 20 USD")

    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed_products()
