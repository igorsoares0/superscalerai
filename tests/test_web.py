import pytest


def test_pages_render(anon_client):
    for path in ("/", "/library", "/login"):
        r = anon_client.get(path)
        assert r.status_code == 200, path
        assert "SuperScaler" in r.text


def test_workspace_lists_presets(anon_client):
    html = anon_client.get("/").text
    for preset in ("portrait", "product", "architecture", "ai-generated"):
        assert f'data-preset="{preset}"' in html


def test_static_js_served(anon_client):
    assert anon_client.get("/static/app.js").status_code == 200


LEGAL_PAGES = ("/terms", "/privacy", "/refunds")


@pytest.mark.parametrize("path", LEGAL_PAGES)
def test_legal_pages_open_without_an_account(anon_client, path):
    """Paddle's reviewer reads these with no session, and so does anyone
    deciding whether to sign up."""
    r = anon_client.get(path)
    assert r.status_code == 200, path
    assert "SuperScaler" in r.text


@pytest.mark.parametrize("path", LEGAL_PAGES)
def test_legal_pages_do_not_load_the_auth_guard(anon_client, path):
    """app.js redirects to /login on any 401 — inheriting base.html would make
    these pages unreadable for exactly the people they exist for."""
    assert "/static/app.js" not in anon_client.get(path).text


@pytest.mark.parametrize("path", LEGAL_PAGES)
def test_legal_pages_link_to_each_other(anon_client, path):
    html = anon_client.get(path).text
    for other in LEGAL_PAGES:
        assert f'href="{other}"' in html, f"{path} is missing a link to {other}"


@pytest.mark.parametrize("path", LEGAL_PAGES)
def test_missing_operator_details_are_loud(anon_client, path, monkeypatch):
    """Dev defaults are empty, so the placeholder has to be impossible to miss.
    In production it can't happen at all: config_problems() makes it fatal."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "legal_contact_email", "")
    assert "set LEGAL_CONTACT_EMAIL in .env" in anon_client.get(path).text


def test_operator_details_come_from_config(anon_client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "legal_entity", "Contoso Imaging Ltda")
    html = anon_client.get("/terms").text
    assert "Contoso Imaging Ltda" in html
    assert "set LEGAL_ENTITY in .env" not in html


def test_signup_page_links_the_policies(anon_client):
    """The only public page a stranger lands on."""
    html = anon_client.get("/login").text
    for path in LEGAL_PAGES:
        assert f'href="{path}"' in html
