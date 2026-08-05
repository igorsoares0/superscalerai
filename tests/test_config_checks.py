import pytest

from app.core.config import (
    SANDBOX_PRICE_BASIC,
    SANDBOX_PRICE_PRO,
    Settings,
    config_problems,
)


def production(**overrides) -> Settings:
    """A production config with nothing wrong with it."""
    base = dict(
        environment="production",
        database_url="postgresql+psycopg://user:pw@host/db",
        replicate_api_token="r8_live",
        paddle_environment="production",
        paddle_api_key="pdl_live_key",
        paddle_client_token="live_token",
        paddle_webhook_secret="pdl_ntfset_live",
        paddle_price_basic="pri_live_basic",
        paddle_price_pro="pri_live_pro",
        cookie_secure=True,
        app_base_url="https://superscaler.example",
        trust_proxy_headers=True,
        r2_bucket="superscaler",
        resend_api_key="re_live",
        email_from="SuperScaler <no-reply@superscaler.example>",
        legal_entity="SuperScaler Ltda",
        legal_address="Rua Exemplo 1, Sao Paulo, Brazil",
        legal_contact_email="support@superscaler.example",
        legal_governing_law="Brazil",
    )
    return Settings(**{**base, **overrides})


def test_dev_defaults_are_never_flagged():
    """The dev defaults ARE the wrong production values — checking them
    outside production would make the app unusable locally."""
    assert config_problems(Settings()) == ([], [])


def test_a_correct_production_config_passes():
    assert config_problems(production()) == ([], [])


@pytest.mark.parametrize(
    "override",
    [
        {"replicate_api_token": ""},
        {"paddle_webhook_secret": ""},
        {"paddle_api_key": ""},
        {"paddle_client_token": ""},
        {"paddle_environment": "sandbox"},
        # PADDLE_ENVIRONMENT can say production while the ids still point at
        # sandbox prices: nothing else in the config contradicts it
        {"paddle_price_basic": SANDBOX_PRICE_BASIC},
        {"paddle_price_pro": SANDBOX_PRICE_PRO},
        {"paddle_price_basic": ""},
        {"paddle_price_pro": ""},
        # no working sender = the password reset link goes to the log, and
        # anyone locked out stays locked out
        {"resend_api_key": ""},
        {"email_from": "SuperScaler <no-reply@example.com>"},
        # the policy pages render a visible placeholder instead of these, and
        # Paddle's approval reads those pages
        {"legal_entity": ""},
        {"legal_address": ""},
        {"legal_contact_email": ""},
        {"legal_governing_law": ""},
        {"legal_entity": "   "},  # whitespace is not a company name
        {"cookie_secure": False},
        {"app_base_url": "http://localhost:8000"},
        {"app_base_url": "http://superscaler.example"},  # https is the point
        {"database_url": "sqlite:///./dev.db"},
    ],
)
def test_each_silent_failure_is_fatal(override):
    fatal, _ = config_problems(production(**override))
    assert len(fatal) == 1, fatal


def test_the_sandbox_defaults_are_what_a_forgotten_swap_looks_like():
    """The whole point of comparing against the constants: a production config
    that simply never touched PADDLE_PRICE_* is the realistic mistake, and it
    has to be caught even though every other Paddle setting is live."""
    fatal, _ = config_problems(
        production(paddle_price_basic=SANDBOX_PRICE_BASIC, paddle_price_pro=SANDBOX_PRICE_PRO)
    )
    assert len(fatal) == 2, fatal


def test_all_problems_are_reported_at_once():
    """One restart per mistake is a bad way to spend a deploy."""
    fatal, _ = config_problems(
        production(replicate_api_token="", paddle_webhook_secret="", cookie_secure=False)
    )
    assert len(fatal) == 3


@pytest.mark.parametrize(
    "override",
    [
        {"rate_limit_enabled": False},
        {"trust_proxy_headers": False},
        {"r2_bucket": ""},
    ],
)
def test_degraded_but_serviceable_config_only_warns(override):
    fatal, warnings = config_problems(production(**override))
    assert fatal == [] and len(warnings) == 1
