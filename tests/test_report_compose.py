import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import web
from app.core import scope as scope_module
from app.core.sessions import save_report
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
    scope.write_text(
        json.dumps({"targets": ["example.com"]}), encoding="utf-8"
    )
    monkeypatch.setenv("DORKS_DATA_PATH", str(corpus))
    monkeypatch.setenv("SCOPE_FILE", str(scope))
    monkeypatch.setenv("EVENTS_FILE", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    web.reset_registry()
    web.reset_adapter()
    scope_module.reset_default_guard()
    c = TestClient(app)
    c.headers["HX-Request"] = "true"
    return c


def test_get_report_without_from_renders_empty_form(client: TestClient) -> None:
    r = client.get("/report")
    body = r.text
    assert r.status_code == 200
    # No prefill banner
    assert 'data-testid="prefill-banner"' not in body
    # Empty fields
    assert 'value=""' in body or 'value=' not in body.replace('value="value="', '')


def test_get_report_from_session_prefills(client: TestClient) -> None:
    saved = save_report(
        target="example.com",
        markdown="## Summary\n\nPrior body.",
        backend="ollama",
        prompt_filename="report_v1.md",
        prompt_hash="a" * 64,
    )
    r = client.get(f"/report?from={saved.session_id}")
    assert r.status_code == 200
    body = r.text
    assert 'data-testid="prefill-banner"' in body
    assert saved.session_id in body
    # Target field pre-filled
    assert 'value="example.com"' in body
    # Session log textarea has the seed content
    assert "Composed from prior session" in body
    assert "Prior body." in body
    assert "Continue below with new findings" in body


def test_get_report_unknown_session_id_renders_empty(client: TestClient) -> None:
    r = client.get("/report?from=20260101-000000-zzzz")
    assert r.status_code == 200
    body = r.text
    assert 'data-testid="prefill-banner"' not in body


def test_get_report_from_traversal_id_renders_empty(client: TestClient) -> None:
    r = client.get("/report?from=../escape")
    assert r.status_code == 200
    body = r.text
    assert 'data-testid="prefill-banner"' not in body


def test_session_detail_has_compose_link(client: TestClient) -> None:
    saved = save_report(
        target="example.com",
        markdown="x",
        backend="ollama",
        prompt_filename="report_v1.md",
        prompt_hash="b" * 64,
    )
    r = client.get(f"/sessions/{saved.session_id}")
    body = r.text
    assert 'data-testid="compose-from-session"' in body
    assert f'href="/report?from={saved.session_id}"' in body
