# Membership Agent

A minimal FastAPI MVP for a compliant membership procurement agent.

--------------------------------------------------

Features

- Quote calculation
- Order creation
- Risk scoring
- NOWPayments checkout
- NOWPayments webhook handling
- Inventory & fulfillment
- Chat assistant

--------------------------------------------------

Quick Start

python -m venv .venv
source .venv/bin/activate   (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
cp .env.example .env

Run server:

uvicorn app.main:app --reload

Health check:

curl http://127.0.0.1:8000/health

Swagger UI:

http://127.0.0.1:8000/docs

--------------------------------------------------

Production URL

https://membership-agent.onrender.com

Swagger:

https://membership-agent.onrender.com/docs

--------------------------------------------------

Environment Variables

DATABASE_URL=your_neon_database_url
ADMIN_INIT_TOKEN=init-123456
ADMIN_PASSWORD=123456
OPENAI_API_KEY=your_openai_key_optional

NOWPAYMENTS_API_KEY=your_nowpayments_api_key
NOWPAYMENTS_IPN_SECRET=your_nowpayments_ipn_secret
NOWPAYMENTS_IPN_CALLBACK_URL=https://membership-agent.onrender.com/webhooks/nowpayments
NOWPAYMENTS_BASE_URL=https://api.nowpayments.io/v1
NOWPAYMENTS_SUCCESS_URL=https://membership-agent.onrender.com/success
NOWPAYMENTS_CANCEL_URL=https://membership-agent.onrender.com/cancel

--------------------------------------------------

IMPORTANT

You MUST initialize the database before using any API.

Step 1:
Open Swagger:
https://membership-agent.onrender.com/docs

Step 2:
Call:
POST /admin/init

Step 3:
Add Header:
x-admin-token: init-123456

--------------------------------------------------

API Flow (Correct Order)

1. /admin/init
2. /quote
3. /orders
4. /payments/checkout
5. User opens invoice_url and pays
6. NOWPayments sends callback to /webhooks/nowpayments

--------------------------------------------------

Example (Mac / Linux)

Quote

curl -X POST https://membership-agent.onrender.com/quote \
-H "Content-Type: application/json" \
-d '{
  "email": "user@example.com",
  "user_type": "team",
  "product_code": "basic_plan",
  "seats": 1
}'

--------------------------------------------------

Create Order

curl -X POST https://membership-agent.onrender.com/orders \
-H "Content-Type: application/json" \
-d '{
  "email": "user@example.com",
  "user_type": "team",
  "product_code": "basic_plan",
  "target_email": "user@example.com",
  "seats": 1
}'

--------------------------------------------------

Create NOWPayments Checkout

curl -X POST https://membership-agent.onrender.com/payments/checkout \
-H "Content-Type: application/json" \
-d '{
  "order_id": "REPLACE_ORDER_ID",
  "pay_currency": "usdttrc20"
}'

--------------------------------------------------

Default Product

basic_plan
price: 10 USD
service_fee: 1 USD

--------------------------------------------------

Notes

- NOWPayments webhook path: /webhooks/nowpayments
- /payments/mock-checkout is kept only for backward compatibility
- /webhooks/mock-payment is kept only for local testing
- Swagger UI is the easiest way to test
