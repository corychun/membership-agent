from uuid import UUID

from pydantic import BaseModel


class MockCheckoutRequest(BaseModel):
    order_id: UUID


class MockWebhookRequest(BaseModel):
    order_id: UUID
    status: str


class CreateUsdtPaymentRequest(BaseModel):
    order_id: UUID


class ConfirmUsdtPaymentRequest(BaseModel):
    admin_password: str
    order_id: UUID
    tx_hash: str
