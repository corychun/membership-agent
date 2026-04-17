from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "membership-agent"
    app_env: str = "dev"
    app_port: int = 8010

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/membership_agent"
    openai_api_key: str | None = None
    admin_review_email: str = "ops@example.com"
    admin_password: str = "123456"
    usdt_trc20_address: str = "TDEMOUSDTTRC20ADDRESSREPLACEME"


settings = Settings()
