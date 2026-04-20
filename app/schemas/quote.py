from pydantic import BaseModel, EmailStr, Field


class QuoteRequest(BaseModel):
    email: EmailStr
    user_type: str = Field(regex="^(individual|team|enterprise)$")
    product_code: str
    seats: int = Field(default=1, ge=1, le=500)


class QuoteResponse(BaseModel):
    official_price: float
    service_fee: float
    total: float
    currency: str
    deliver_method: str
    needs_manual_review: bool
    risk_score: int
    flags: list[str]
