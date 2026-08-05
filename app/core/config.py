from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The sandbox catalog (product pro_01kxhfxj722hfs6bqpfhcs46d1), and the dev
# default so a fresh clone can open a checkout with no config at all.
# Paddle price ids are `pri_01...` in BOTH environments — nothing in the string
# says which one it belongs to — so "did anyone swap these for the live ones?"
# is only answerable by comparing against these constants.
SANDBOX_PRICE_BASIC = "pri_01kxhgnzn8v3hmx52s8fc8dmzn"
SANDBOX_PRICE_PRO = "pri_01kxhgnzse29n9pg7sz5y74jmp"


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
    # Checkout catalog. Only the ids live here: the monthly allowance is read
    # from the price's custom_data at webhook time (see services/billing.py).
    paddle_price_basic: str = SANDBOX_PRICE_BASIC
    paddle_price_pro: str = SANDBOX_PRICE_PRO
    resend_api_key: str = ""  # empty = emails are logged instead of sent (dev)
    email_from: str = "SuperScaler <no-reply@example.com>"
    app_base_url: str = "http://localhost:8000"  # base for links inside emails
    password_reset_ttl_minutes: int = 30
    # Who is selling, and under whose law. Rendered on /terms, /privacy and
    # /refunds — pages Paddle reads during approval and customers read when
    # they want their money back. Empty shows a loud placeholder in the page
    # and is fatal in production: publishing a policy that says "[set this]"
    # is worse than publishing none.
    legal_entity: str = ""  # registered name, e.g. "Jane Doe ME" or a company
    legal_address: str = ""  # postal address, one line
    legal_contact_email: str = ""  # a mailbox a human reads, e.g. support@...
    legal_governing_law: str = ""  # e.g. "Brazil" — which courts and law apply
    # Buyers in the EU/UK have a statutory 14-day withdrawal right, so a
    # shorter window than this would be unenforceable there anyway.
    refund_window_days: int = 14


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
    # PADDLE_ENVIRONMENT alone doesn't cover this: pointing the live API at a
    # sandbox price id passes every other check, boots clean, and then every
    # checkout either fails or bills nothing.
    for name, value, sandbox in (
        ("PADDLE_PRICE_BASIC", s.paddle_price_basic, SANDBOX_PRICE_BASIC),
        ("PADDLE_PRICE_PRO", s.paddle_price_pro, SANDBOX_PRICE_PRO),
    ):
        if not value:
            fatal.append(f"{name} is empty — that plan's checkout can't open")
        elif value == sandbox:
            fatal.append(f"{name} is still the sandbox price — it takes no real money")
    if not s.cookie_secure:
        fatal.append("COOKIE_SECURE is off — session cookies would travel in plain HTTP")
    if not s.app_base_url.startswith("https://") or "localhost" in s.app_base_url:
        fatal.append(f"APP_BASE_URL is {s.app_base_url!r} — password reset links would be broken")
    if s.database_url.startswith("sqlite"):
        fatal.append("DATABASE_URL still points at SQLite — production runs on Neon")
    # Password reset is the ONLY way back into an account. Without a working
    # sender the link is written to the log and nowhere else: the app looks
    # healthy while every locked-out user stays locked out, and the only signal
    # is a support ticket.
    if not s.resend_api_key:
        fatal.append("RESEND_API_KEY is empty — password reset emails would only be logged")
    if "example.com" in s.email_from:
        fatal.append(
            f"EMAIL_FROM is still {s.email_from!r} — Resend refuses to send from "
            "a domain that isn't verified"
        )
    # The legal pages render a visible placeholder wherever one of these is
    # blank. Serving that to a customer (or to Paddle's reviewer) is a worse
    # outcome than refusing to boot.
    for name, value in (
        ("LEGAL_ENTITY", s.legal_entity),
        ("LEGAL_ADDRESS", s.legal_address),
        ("LEGAL_CONTACT_EMAIL", s.legal_contact_email),
        ("LEGAL_GOVERNING_LAW", s.legal_governing_law),
    ):
        if not value.strip():
            fatal.append(f"{name} is empty — /terms, /privacy and /refunds would show a placeholder")

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
    return fatal, warnings
