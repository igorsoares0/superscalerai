"""Transactional email via Resend's HTTP API.

Without RESEND_API_KEY the message body is logged instead of sent, so the
password-reset flow works in dev by copying the link from the server log.
Senders run inside BackgroundTasks: failures must be logged, never raised
into a response.
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


def send_email(to: str, subject: str, html: str, text: str) -> None:
    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not set; email to %s not sent:\n%s", to, text)
        return
    try:
        r = httpx.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key.get_secret_value()}"},
            json={
                "from": settings.email_from,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            },
            timeout=10,
        )
        r.raise_for_status()
        logger.info("email sent to %s (%s)", to, r.json().get("id"))
    except httpx.HTTPError:
        logger.exception("failed to send email to %s", to)


def send_verification(to: str, verify_url: str) -> None:
    credits = settings.signup_bonus_credits
    hours = settings.email_verification_ttl_hours
    reward = f" and collect your {credits} free credits" if credits > 0 else ""
    text = (
        "Welcome to SuperScaler!\n\n"
        f"Confirm this address{reward} (link expires in {hours} hours):\n{verify_url}\n\n"
        "If you didn't sign up, you can ignore this email — the account stays "
        "empty and unusable without this confirmation."
    )
    html = f"""\
<div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;padding:24px">
  <h2 style="margin:0 0 16px">Confirm your email</h2>
  <p style="color:#444;line-height:1.5">Welcome to SuperScaler! Confirm this
  address{reward}. This link expires in {hours} hours.</p>
  <p style="margin:24px 0">
    <a href="{verify_url}" style="background:#4b72ff;color:#fff;padding:10px 20px;
       border-radius:8px;text-decoration:none;font-weight:600">Confirm my email</a>
  </p>
  <p style="color:#888;font-size:13px;line-height:1.5">If you didn't sign up, you can
  ignore this email — the account stays empty and unusable without this confirmation.</p>
</div>"""
    send_email(to, "Confirm your SuperScaler email", html, text)


def send_password_reset(to: str, reset_url: str) -> None:
    minutes = settings.password_reset_ttl_minutes
    text = (
        "Someone asked to reset the password of your SuperScaler account.\n\n"
        f"Reset it here (link expires in {minutes} minutes):\n{reset_url}\n\n"
        "If it wasn't you, you can ignore this email — your password stays the same."
    )
    html = f"""\
<div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;padding:24px">
  <h2 style="margin:0 0 16px">Reset your SuperScaler password</h2>
  <p style="color:#444;line-height:1.5">Someone asked to reset the password of your
  SuperScaler account. This link expires in {minutes} minutes.</p>
  <p style="margin:24px 0">
    <a href="{reset_url}" style="background:#4b72ff;color:#fff;padding:10px 20px;
       border-radius:8px;text-decoration:none;font-weight:600">Choose a new password</a>
  </p>
  <p style="color:#888;font-size:13px;line-height:1.5">If it wasn't you, you can ignore
  this email — your password stays the same.</p>
</div>"""
    send_email(to, "Reset your SuperScaler password", html, text)
