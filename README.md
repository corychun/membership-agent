# Membership Agent

A minimal FastAPI MVP for a compliant membership procurement agent.

--------------------------------------------------

Features

- Quote calculation
- Order creation
- Risk scoring
- Mock payment flow
- Webhook handling
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
OPENAI_API_KEY=optional

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

1. /admin/init          (setup database)
2. /quote               (get price)
3. /orders              (create order)
4. /payments/mock-checkout (simulate payment)
5. /webhooks/mock-payment  (mark as paid)

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

Mock Payment

curl -X POST https://membership-agent.onrender.com/payments/mock-checkout \
-H "Content-Type: application/json" \
-d '{
  "order_id": "REPLACE_ORDER_ID"
}'

--------------------------------------------------

Mock Webhook

curl -X POST https://membership-agent.onrender.com/webhooks/mock-payment \
-H "Content-Type: application/json" \
-d '{
  "order_id": "REPLACE_ORDER_ID",
  "status": "paid"
}'

--------------------------------------------------

Windows CMD Version

Replace "\" with "^"

Example:

curl -X POST https://membership-agent.onrender.com/quote ^
-H "Content-Type: application/json" ^
-d "{ 
  \"email\": \"user@example.com\",
  \"user_type\": \"team\",
  \"product_code\": \"basic_plan\",
  \"seats\": 1
}"

--------------------------------------------------

Default Product

basic_plan
price: 10 USD
service_fee: 1 USD

--------------------------------------------------

Notes

- Payment is mocked (no Stripe yet)
- /admin/init is required before use
- Swagger UI is the easiest way to test
- Ready for Stripe integration
