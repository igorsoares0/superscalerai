from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    replicate_api_token: str = ""
    storage_dir: Path = Path("storage")
    # R2 (S3-compatible) object storage; all four set -> S3 backend,
    # otherwise files stay on local disk (dev default)
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    max_upload_mb: int = 25
    # Longest input edge. GPU cost grows ~quadratically with size (~$0.08 at
    # 1792px 2x) while the credit price caps at 4 credits, so huge inputs run
    # at a loss besides being slow/flaky on the provider.
    max_image_px: int = 3072
    max_concurrent_jobs: int = 4  # Replicate 429s around 8 parallel predictions
    rate_limit_enabled: bool = True
    trust_proxy_headers: bool = False  # True only behind a proxy that overwrites X-Forwarded-For
    login_rate_limit: int = 5  # per IP and per email (brute-force)
    login_rate_window_minutes: int = 15
    register_rate_limit: int = 3  # per IP; every signup mints bonus credits (real GPU money)
    register_rate_window_minutes: int = 60
    forgot_rate_limit: int = 3  # per IP and per email; every hit sends a real email
    forgot_rate_window_minutes: int = 60
    upload_rate_limit: int = 20  # per user
    upload_rate_window_minutes: int = 1
    session_ttl_days: int = 30
    # must cover one job at the top credit tier: the trial has to work with
    # whatever photo the user actually has (a phone photo lands on the 8 tier)
    signup_bonus_credits: int = 8
    cookie_secure: bool = False  # True behind HTTPS in production
    paddle_environment: str = "sandbox"  # "sandbox" | "production"
    paddle_api_key: str = ""  # server-side API key (cancel subscriptions etc.)
    paddle_client_token: str = ""  # client-side token, safe to expose to the browser
    paddle_webhook_secret: str = ""  # notification-setting endpoint secret (pdl_ntfset_...)
    paddle_webhook_max_age_seconds: int = 300
    resend_api_key: str = ""  # empty = emails are logged instead of sent (dev)
    email_from: str = "SuperScaler <no-reply@example.com>"
    app_base_url: str = "http://localhost:8000"  # base for links inside emails
    password_reset_ttl_minutes: int = 30


settings = Settings()
