from pydantic import BaseModel, EmailStr, Field


class CreateOrderRequest(BaseModel):
    email: EmailStr
    user_type: str = Field(regex="^(individual|team|enterprise)$")
    product_code: str
    target_email: EmailStr
    seats: int = Field(default=1, ge=1, le=500)


class CreateOrderResponse(BaseModel):
    order_id: str
    status: str
    payment_status: str
    review_status: str
    delivery_status: str
    amount: float
    currency: str
