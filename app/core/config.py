from pydantic import BaseSettings
import os


class Settings(BaseSettings):
    app_name: str = "membership-agent"
    app_env: str = "dev"
    app_port: int = 8010

    # ✅ 优先用环境变量（Render）
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/membership_agent"
    )

    openai_api_key: str | None = None
    admin_review_email: str = "ops@example.com"
    admin_password: str = os.getenv("ADMIN_PASSWORD", "123456")
    usdt_trc20_address: str = "TDEMOUSDTTRC20ADDRESSREPLACEME"

    class Config:
        env_file = ".env"


settings = Settings()
