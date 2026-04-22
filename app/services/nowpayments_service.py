import hashlib
import hmac
import json
from typing import Any

import requests

from app.core.config import settings


def _headers() -> dict:
    if not settings.nowpayments_api_key:
        raise ValueError("NOWPAYMENTS_API_KEY is not set")

    return {
        "x-api-key": settings.nowpayments_api_key,
        "Content-Type": "application/json",
    }


def _sort_object(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sort_object(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_sort_object(x) for x in obj]
    return obj


def create_invoice(order, pay_currency: str = "usdttrc20") -> dict:
    url = f"{settings.nowpayments_base_url}/invoice"

    payload = {
        "price_amount": float(order.amount_usd),
        "price_currency": "usd",
        "pay_currency": pay_currency,
        "order_id": str(order.order_no),
        "order_description": f"Membership order {order.product_code}",
        "ipn_callback_url": settings.nowpayments_ipn_callback_url,
        "success_url": settings.nowpayments_success_url,
        "cancel_url": settings.nowpayments_cancel_url,
        "customer_email": getattr(order, "customer_email", None),
    }

    response = requests.post(url, headers=_headers(), json=payload, timeout=30)

    try:
        data = response.json()
    except Exception:
        data = {"raw_text": response.text}

    if response.status_code >= 400:
        raise ValueError(f"NOWPayments error: {data}")

    return data


def verify_ipn_signature(raw_body: bytes, signature: str | None) -> bool:
    if not signature:
        return False

    if not settings.nowpayments_ipn_secret:
        return False

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return False

    sorted_payload = _sort_object(payload)
    sorted_json = json.dumps(sorted_payload, separators=(",", ":"), ensure_ascii=False)

    expected = hmac.new(
        settings.nowpayments_ipn_secret.encode("utf-8"),
        sorted_json.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)
