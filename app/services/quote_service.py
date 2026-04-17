from app.models.entities import Product


def build_quote(product: Product, seats: int) -> dict:
    official_price = float(product.official_price) * seats
    service_fee = float(product.service_fee) * seats
    total = official_price + service_fee
    return {
        "official_price": official_price,
        "service_fee": service_fee,
        "total": total,
        "currency": product.currency,
        "deliver_method": product.deliver_method,
    }
