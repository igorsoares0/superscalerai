from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    replicate_api_token: str = ""
    storage_dir: Path = Path("storage")
    max_upload_mb: int = 25
    session_ttl_days: int = 30
    signup_bonus_credits: int = 3
    cookie_secure: bool = False  # True behind HTTPS in production
    paddle_environment: str = "sandbox"  # "sandbox" | "production"
    paddle_client_token: str = ""  # client-side token, safe to expose to the browser
    paddle_webhook_secret: str = ""  # notification-setting endpoint secret (pdl_ntfset_...)
    paddle_webhook_max_age_seconds: int = 300
    resend_api_key: str = ""  # empty = emails are logged instead of sent (dev)
    email_from: str = "SuperScaler <no-reply@example.com>"
    app_base_url: str = "http://localhost:8000"  # base for links inside emails
    password_reset_ttl_minutes: int = 30


settings = Settings()
