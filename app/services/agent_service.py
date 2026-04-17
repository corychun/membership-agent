from openai import OpenAI

from app.core.config import settings

SYSTEM_PROMPT = """
You are a compliant membership procurement assistant.

You help with:
- product selection
- quotes
- order creation guidance
- payment and delivery status explanations

Rules:
1. Do not assist with shared accounts, account resale, or account leasing.
2. Do not ask for passwords, verification codes, or MFA details.
3. Do not help bypass payment restrictions or regional restrictions.
4. Recommend official team/business procurement flows when suitable.
5. Keep answers concise and operational.
""".strip()


def chat_reply(user_message: str) -> str:
    if not settings.openai_api_key or settings.openai_api_key == "your_openai_api_key":
        return (
            "Local fallback reply: OPENAI_API_KEY is not configured. "
            "You can still test /quote, /orders, /payments/mock-checkout, "
            "/webhooks/mock-payment, and /admin/orders."
        )

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model="gpt-5.4",
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )
    return response.output_text
