# Membership Agent (Codex-ready)

A minimal FastAPI MVP for a compliant membership procurement agent:
- quote
- order creation
- basic risk scoring
- mock payment link generation
- webhook callback
- manual delivery queue
- chat assistant endpoint

## 1) Quick start

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`, then create a PostgreSQL database named `membership_agent`.

Run:

```bash
uvicorn app.main:app --reload
```

Healthcheck:

```bash
curl http://127.0.0.1:8000/health
```

## 2) Recommended Codex task prompt

Copy this into Codex after opening the repo:

```text
You are working on a FastAPI project called membership-agent.

Goal:
1. Install dependencies.
2. Create the PostgreSQL schema if migrations are not present.
3. Start the app locally.
4. Test /health, /quote, /orders, /payments/mock-checkout, /webhooks/mock-payment.
5. Fix any startup or import issues.
6. Keep the project compliant: do not add shared-account flows, password collection, region-bypass logic, or resale/account-leasing features.
7. If environment variables are missing, create a .env from .env.example and clearly mark placeholders that still need manual values.
8. Prefer small safe edits and explain each change in the final summary.

Expected outcome:
- Server runs successfully
- Endpoints respond correctly
- README startup steps match the real code
```

## 3) Endpoints

- `GET /health`
- `POST /quote`
- `POST /orders`
- `POST /payments/mock-checkout`
- `POST /webhooks/mock-payment`
- `POST /deliveries/{order_id}/complete`
- `POST /chat`

## 4) Example calls

### Quote
```bash
curl -X POST http://127.0.0.1:8000/quote \
  -H "Content-Type: application/json" \
  -d '{
    "email":"user@example.com",
    "user_type":"team",
    "product_code":"chatgpt-business-monthly",
    "seats":3
  }'
```

### Create order
```bash
curl -X POST http://127.0.0.1:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "email":"user@example.com",
    "user_type":"team",
    "product_code":"chatgpt-business-monthly",
    "target_email":"user@example.com",
    "seats":3
  }'
```

### Mock payment
```bash
curl -X POST http://127.0.0.1:8000/payments/mock-checkout \
  -H "Content-Type: application/json" \
  -d '{
    "order_id":"REPLACE_ORDER_ID"
  }'
```

### Mock webhook
```bash
curl -X POST http://127.0.0.1:8000/webhooks/mock-payment \
  -H "Content-Type: application/json" \
  -d '{
    "order_id":"REPLACE_ORDER_ID",
    "status":"paid"
  }'
```

## 5) Notes

- Payment is mocked on purpose so Codex can run the MVP without Stripe credentials.
- The chat endpoint uses the OpenAI Responses API if `OPENAI_API_KEY` is set; otherwise it falls back to a local canned response.
- First version uses manual delivery completion to keep the workflow safe and auditable.
