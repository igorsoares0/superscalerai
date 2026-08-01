from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "dev"  # "production" turns on the boot checks below
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
    # A prediction that never settles would hold its slot forever and stall the
    # queue for everyone. Generous: a cold model on Replicate can take minutes
    # to boot before the ~60s of GPU work.
    prediction_timeout_seconds: int = 600
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


def config_problems(s: Settings) -> tuple[list[str], list[str]]:
    """(fatal, warnings) for the current configuration.

    Every one of these has a silent failure mode: the app boots, serves, and
    quietly does the wrong thing — sessions over plain HTTP, webhooks rejected
    while customers are charged, reset links pointing at localhost. Cheaper to
    refuse to start than to find out from a user. Only checked when
    environment=production, since the defaults are all correct for dev."""
    if s.environment != "production":
        return [], []

    fatal = []
    if not s.replicate_api_token:
        fatal.append("REPLICATE_API_TOKEN is empty — every job would fail")
    if not s.paddle_webhook_secret:
        fatal.append(
            "PADDLE_WEBHOOK_SECRET is empty — every webhook is rejected, so "
            "customers would be charged and get no credits"
        )
    if not s.paddle_api_key:
        fatal.append("PADDLE_API_KEY is empty — plan changes and cancellations would fail")
    if not s.paddle_client_token:
        fatal.append("PADDLE_CLIENT_TOKEN is empty — the checkout can't open")
    if s.paddle_environment != "production":
        fatal.append(
            f"PADDLE_ENVIRONMENT is {s.paddle_environment!r} — sandbox prices take no real money"
        )
    if not s.cookie_secure:
        fatal.append("COOKIE_SECURE is off — session cookies would travel in plain HTTP")
    if not s.app_base_url.startswith("https://") or "localhost" in s.app_base_url:
        fatal.append(f"APP_BASE_URL is {s.app_base_url!r} — password reset links would be broken")
    if s.database_url.startswith("sqlite"):
        fatal.append("DATABASE_URL still points at SQLite — production runs on Neon")

    warnings = []
    if not s.rate_limit_enabled:
        warnings.append("rate limiting is disabled")
    if not s.trust_proxy_headers:
        warnings.append(
            "TRUST_PROXY_HEADERS is off — behind a reverse proxy every client "
            "looks like one IP, so per-IP limits throttle everyone together"
        )
    if not s.r2_bucket:
        warnings.append("no R2 bucket configured — uploads and results stay on the local disk")
    if not s.resend_api_key:
        warnings.append("RESEND_API_KEY is empty — password reset emails are only logged")
    if "example.com" in s.email_from:
        warnings.append(f"EMAIL_FROM is still {s.email_from!r}")
    return fatal, warnings
