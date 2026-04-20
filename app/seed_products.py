from app.core.db import SessionLocal
from app.models.entities import Product


def seed_products():
    db = SessionLocal()
    try:
        existing = db.query(Product).filter(Product.code == "basic_plan").first()

        if existing:
            print("⏭ basic_plan exists, skip")
            return

        p = Product(
            code="basic_plan",
            provider="openai",
            official_plan_name="Basic",
            billing_cycle="monthly",
            official_price=10,
            currency="USD",
            service_fee=1,
            deliver_method="api",
            is_active=True
        )

        db.add(p)
        db.commit()
        print("✅ basic_plan created")

    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed_products()