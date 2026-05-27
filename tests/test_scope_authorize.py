import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import web
from app.core import scope as scope_module
from app.core.scope import ScopeGuard
from app.main import app


def _seed_corpus(root: Path) -> None:
    cat = root / "SQLi"
    cat.mkdir()
    (cat / "basic.txt").write_text("site:{target} inurl:id=\n", encoding="utf-8")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _seed_corpus(corpus)
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"targets": ["example.com"]}), encoding="utf-8")
    monkeypatch.setenv("DORKS_DATA_PATH", str(corpus))
    monkeypatch.setenv("SCOPE_FILE", str(scope))
    monkeypatch.setenv("EVENTS_FILE", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    web.reset_registry()
    web.reset_adapter()
    scope_module.reset_default_guard()
    return TestClient(app, follow_redirects=False)


def test_add_target_appends_to_scope_file(tmp_path: Path) -> None:
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"targets": ["example.com"]}), encoding="utf-8")
    guard = ScopeGuard(scope)
    assert guard.add_target("new.com") is True
    raw = json.loads(scope.read_text(encoding="utf-8"))
    assert "new.com" in raw["targets"]
    # Idempotent: a second call returns False
    assert ScopeGuard(scope).add_target("new.com") is False


def test_add_target_creates_file_when_missing(tmp_path: Path) -> None:
    scope = tmp_path / "absent.json"
    guard = ScopeGuard(scope)
    assert guard.add_target("fresh.com") is True
    assert scope.is_file()
    raw = json.loads(scope.read_text(encoding="utf-8"))
    assert raw["targets"] == ["fresh.com"]


def test_add_target_normalizes_case_and_dot(tmp_path: Path) -> None:
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"targets": []}), encoding="utf-8")
    guard = ScopeGuard(scope)
    guard.add_target("EXAMPLE.com.")
    raw = json.loads(scope.read_text(encoding="utf-8"))
    assert "example.com" in raw["targets"]


def test_add_target_accepts_wildcard(tmp_path: Path) -> None:
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"targets": []}), encoding="utf-8")
    guard = ScopeGuard(scope)
    guard.add_target("*.example.com")
    raw = json.loads(scope.read_text(encoding="utf-8"))
    assert "*.example.com" in raw["targets"]


def test_post_authorize_redirects_and_adds(
    client: TestClient, tmp_path: Path
) -> None:
    r = client.post(
        "/scope/authorize",
        data={"target": "evil.com", "next_path": "/query"},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/query"
    raw = json.loads((tmp_path / "scope.json").read_text(encoding="utf-8"))
    assert "evil.com" in raw["targets"]


def test_post_authorize_rejects_external_redirect(client: TestClient) -> None:
    r = client.post(
        "/scope/authorize",
        data={"target": "evil.com", "next_path": "https://attacker.example/"},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_post_authorize_empty_target_400(client: TestClient) -> None:
    r = client.post(
        "/scope/authorize", data={"target": "", "next_path": "/"}
    )
    assert r.status_code == 400


def test_query_error_template_renders_authorize_button(
    client: TestClient,
) -> None:
    """Sanity check: the partial template includes the authorize button block
    when target is set and reason is 'out of scope'."""
    from fastapi.templating import Jinja2Templates

    t = Jinja2Templates(directory="app/templates")
    # The partial expects a request; for direct template tests we pass None
    # but the new template only consults request.url.path if request is truthy,
    # so an empty dict still renders.
    rendered = t.get_template("_query_error.html").render(
        request=None,
        reason="out of scope",
        detail="target out of scope: 'evil.com'",
        target="evil.com",
    )
    assert 'data-testid="authorize-block"' in rendered
    assert 'data-testid="authorize-button"' in rendered
    assert 'value="evil.com"' in rendered
