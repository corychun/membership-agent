from fastapi import APIRouter, Request
import json
import hmac
import hashlib
import os

router = APIRouter()

NOWPAYMENTS_IPN_SECRET = os.getenv("NOWPAYMENTS_IPN_SECRET", "")

@router.post("/webhooks/nowpayments")
async def nowpayments_webhook(request: Request):
    try:
        # ✅ 用 stream 方式读取（关键修复）
        body_bytes = b""
        async for chunk in request.stream():
            body_bytes += chunk

        raw_body = body_bytes.decode()

        data = json.loads(raw_body)

        # ===== 验证签名 =====
        received_sig = request.headers.get("x-nowpayments-sig")

        if NOWPAYMENTS_IPN_SECRET:
            expected_sig = hmac.new(
                NOWPAYMENTS_IPN_SECRET.encode(),
                raw_body.encode(),
                hashlib.sha512
            ).hexdigest()

            if received_sig != expected_sig:
                print("❌ IPN 签名验证失败")
                return {"status": "error"}

        # ===== 处理支付 =====
        payment_status = data.get("payment_status")
        order_id = data.get("order_id")

        print("✅ 收到回调:", data)

        if payment_status in ["finished", "confirmed"]:
            from app.services.orders import mark_order_paid

            mark_order_paid(order_id)

        return {"status": "ok"}

    except Exception as e:
        print("❌ webhook error:", str(e))
        return {"status": "error"}
