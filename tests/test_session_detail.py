import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import web
from app.core import scope as scope_module
from app.core.sessions import get_session, save_report
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
    return TestClient(app)


def test_get_session_returns_none_for_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    assert get_session("nope") is None


def test_get_session_rejects_path_traversal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    for bad in ("../escape", "..", "foo/bar", "foo\\bar"):
        assert get_session(bad) is None


def test_session_detail_page_renders(client: TestClient) -> None:
    saved = save_report(
        target="example.com",
        markdown="## Summary\n\nFull body",
        backend="ollama",
        prompt_filename="report_v1.md",
        prompt_hash="a" * 64,
    )
    r = client.get(f"/sessions/{saved.session_id}")
    assert r.status_code == 200
    body = r.text
    assert "Session" in body
    assert saved.session_id in body
    assert "## Summary" in body
    assert 'data-testid="session-meta"' in body
    assert 'data-testid="download-report"' in body
    assert 'href="/sessions/{}/report.md"'.format(saved.session_id) in body


def test_session_detail_unknown_returns_404(client: TestClient) -> None:
    r = client.get("/sessions/nope-session-id")
    assert r.status_code == 404
    assert "session not found" in r.text.lower()


def test_session_report_download_serves_markdown(client: TestClient) -> None:
    saved = save_report(
        target="example.com",
        markdown="## Title\n\nbody.",
        backend="ollama",
        prompt_filename="report_v1.md",
        prompt_hash="b" * 64,
    )
    r = client.get(f"/sessions/{saved.session_id}/report.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.text == "## Title\n\nbody."


def test_session_report_download_404_for_missing(client: TestClient) -> None:
    r = client.get("/sessions/nope-session/report.md")
    assert r.status_code == 404


def test_sessions_index_links_to_detail(client: TestClient) -> None:
    saved = save_report(
        target="example.com",
        markdown="x",
        backend="ollama",
        prompt_filename="report_v1.md",
        prompt_hash="c" * 64,
    )
    r = client.get("/sessions")
    assert r.status_code == 200
    assert f'href="/sessions/{saved.session_id}"' in r.text
