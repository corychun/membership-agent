import os
import stripe

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


def create_checkout_session(order):
    if not stripe.api_key:
        raise Exception("STRIPE_SECRET_KEY not set")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"Membership - {order.product_code}",
                    },
                    "unit_amount": int(order.amount * 100),
                },
                "quantity": 1,
            }
        ],
        metadata={
            "order_id": str(order.id)
        },
        success_url=os.getenv("STRIPE_SUCCESS_URL"),
        cancel_url=os.getenv("STRIPE_CANCEL_URL"),
    )

    return session.url