from pydantic import BaseModel, EmailStr, Field


class QuoteRequest(BaseModel):
    email: EmailStr = Field(example="user@example.com")

    user_type: str = Field(
        default="individual",
        regex="^(individual|team|enterprise)$",
        example="team"
    )

    product_code: str = Field(
        default="basic_plan",
        example="basic_plan"
    )

    seats: int = Field(
        default=1,
        ge=1,
        le=500,
        example=1
    )


class QuoteResponse(BaseModel):
    official_price: float
    service_fee: float
    total: float
    currency: str
    deliver_method: str
    needs_manual_review: bool
    risk_score: int
    flags: list[str]
