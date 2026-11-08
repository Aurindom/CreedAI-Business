import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "site" / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>SPA SHELL</html>")
    (root / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "site" / "secret.txt").write_text("TOP SECRET")
    monkeypatch.setenv("FRONTEND_DIST", str(root))
    return root


def test_index_and_asset_served(client, dist):
    assert "SPA SHELL" in client.get("/").text
    assert client.get("/assets/app.js").text == "console.log(1)"


def test_spa_fallback_for_client_routes(client, dist):
    res = client.get("/compare/some-business")
    assert res.status_code == 200 and "SPA SHELL" in res.text


def test_missing_asset_is_404_not_index(client, dist):
    res = client.get("/assets/missing.js")
    assert res.status_code == 404 and "SPA SHELL" not in res.text


def test_api_routes_not_shadowed(client, dist):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_unknown_api_path_is_json_404(client, dist):
    res = client.get("/api/nope/at/all")
    assert res.status_code == 404
    assert res.headers["content-type"].startswith("application/json")
    assert "SPA SHELL" not in res.text


def test_post_to_unknown_path_not_served_as_page(client, dist):
    assert client.post("/somewhere").status_code == 404


@pytest.mark.parametrize("path", ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt", "/..%2fsecret.txt", "/%2e%2e%2fsecret.txt"])
def test_no_path_traversal(client, dist, path):
    assert "TOP SECRET" not in client.get(path).text


def test_no_dist_leaves_api_as_before(client, tmp_path, monkeypatch):
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path / "absent"))
    assert client.get("/api/health").status_code == 200
    res = client.get("/")
    assert res.status_code == 404 and res.json() == {"detail": "Not Found"}


def test_unhandled_error_is_plain_json_and_logged(tmp_path, monkeypatch, caplog):
    router = APIRouter()

    @router.get("/api/_w07_boom")
    def boom():
        raise RuntimeError("secret internal detail /srv/app/x.py")

    app.include_router(router)
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            with caplog.at_level("ERROR", logger="app.web"):
                res = c.get("/api/_w07_boom")
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/api/_w07_boom"]
    assert res.status_code == 500
    body = res.text
    assert "Traceback" not in body and "secret internal detail" not in body and "RuntimeError" not in body
    assert set(res.json()) == {"detail"}
    assert "secret internal detail" in caplog.text
