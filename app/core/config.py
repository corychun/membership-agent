import os
from pydantic import BaseSettings


class Settings(BaseSettings):
    app_name: str = "membership-agent"
    app_env: str = "dev"
    app_port: int = 8010

    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/membership_agent"
    )

    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    admin_review_email: str = "ops@example.com"
    admin_password: str = os.getenv("ADMIN_PASSWORD", "123456")
    usdt_trc20_address: str = "TDEMOUSDTTRC20ADDRESSREPLACEME"

    nowpayments_api_key: str | None = os.getenv("NOWPAYMENTS_API_KEY")
    nowpayments_ipn_secret: str | None = os.getenv("NOWPAYMENTS_IPN_SECRET")
    nowpayments_ipn_callback_url: str = os.getenv(
        "NOWPAYMENTS_IPN_CALLBACK_URL",
        "https://membership-agent.onrender.com/webhooks/nowpayments"
    )
    nowpayments_base_url: str = os.getenv(
        "NOWPAYMENTS_BASE_URL",
        "https://api.nowpayments.io/v1"
    )
    nowpayments_success_url: str = os.getenv(
        "NOWPAYMENTS_SUCCESS_URL",
        "https://membership-agent.onrender.com/success"
    )
    nowpayments_cancel_url: str = os.getenv(
        "NOWPAYMENTS_CANCEL_URL",
        "https://membership-agent.onrender.com/cancel"
    )

    class Config:
        env_file = ".env"


settings = Settings()
