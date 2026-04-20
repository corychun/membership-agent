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
source .venv/bin/activate
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

First Step (IMPORTANT)

Initialize database:

POST /admin/init

Header:
x-admin-token: init-123456

--------------------------------------------------

API Flow

1. /quote
2. /orders
3. /payments/mock-checkout
4. /webhooks/mock-payment

--------------------------------------------------

Example

Quote

curl -X POST https://membership-agent.onrender.com/quote ^
-H "Content-Type: application/json" ^
-d "{ 
  \"email\": \"user@example.com\",
  \"user_type\": \"team\",
  \"product_code\": \"basic_plan\",
  \"seats\": 1
}"

--------------------------------------------------

Create Order

curl -X POST https://membership-agent.onrender.com/orders ^
-H "Content-Type: application/json" ^
-d "{ 
  \"email\": \"user@example.com\",
  \"user_type\": \"team\",
  \"product_code\": \"basic_plan\",
  \"target_email\": \"user@example.com\",
  \"seats\": 1
}"

--------------------------------------------------

Mock Payment

curl -X POST https://membership-agent.onrender.com/payments/mock-checkout ^
-H "Content-Type: application/json" ^
-d "{ 
  \"order_id\": \"REPLACE_ORDER_ID\"
}"

--------------------------------------------------

Mock Webhook

curl -X POST https://membership-agent.onrender.com/webhooks/mock-payment ^
-H "Content-Type: application/json" ^
-d "{ 
  \"order_id\": \"REPLACE_ORDER_ID\",
  \"status\": \"paid\"
}"

--------------------------------------------------

Default Product

basic_plan
price: 10 USD
service_fee: 1 USD

--------------------------------------------------

Notes

- Payment is mocked
- /admin/init is for setup only
- Ready for Stripe integration
