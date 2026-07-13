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
