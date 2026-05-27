import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import web
from app.core import scope as scope_module
from app.core.sessions import list_sessions, save_report
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


def test_list_sessions_empty_when_no_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "absent"))
    assert list_sessions() == []


def test_list_sessions_returns_newest_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("EVENTS_FILE", str(tmp_path / "events.jsonl"))
    first = save_report(
        target="example.com",
        markdown="A",
        backend="ollama",
        prompt_filename="report_v1.md",
        prompt_hash="a" * 64,
    )
    time.sleep(0.01)
    second = save_report(
        target="other.example.com",
        markdown="B",
        backend="groq",
        prompt_filename="report_v1.md",
        prompt_hash="b" * 64,
    )
    sessions = list_sessions()
    assert [s.session_id for s in sessions[:2]] == [
        second.session_id,
        first.session_id,
    ]


def test_list_sessions_skips_missing_meta(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    monkeypatch.setenv("SESSIONS_DIR", str(root))
    # One legit session dir, one with no meta.json
    valid = root / "20260527-080000-aaaa"
    valid.mkdir()
    (valid / "report.md").write_text("x", encoding="utf-8")
    (valid / "meta.json").write_text(
        json.dumps(
            {
                "session_id": "20260527-080000-aaaa",
                "target": "example.com",
                "backend": "ollama",
                "ts": "2026-05-27T08:00:00+00:00",
                "prompt_filename": "report_v1.md",
            }
        ),
        encoding="utf-8",
    )
    orphan = root / "20260527-090000-bbbb"
    orphan.mkdir()
    sessions = list_sessions()
    assert len(sessions) == 1
    assert sessions[0].session_id == "20260527-080000-aaaa"


def test_get_sessions_page_renders_empty(client: TestClient) -> None:
    r = client.get("/sessions")
    assert r.status_code == 200
    body = r.text
    assert "Saved sessions" in body
    assert "0 sessions on disk" in body or "No saved sessions yet" in body


def test_get_sessions_page_lists_saved(
    client: TestClient, tmp_path: Path
) -> None:
    save_report(
        target="example.com",
        markdown="## Summary\n\nX",
        backend="ollama",
        prompt_filename="report_v1.md",
        prompt_hash="a" * 64,
    )
    r = client.get("/sessions")
    body = r.text
    assert 'data-testid="sessions-list"' in body
    assert "example.com" in body
    assert "ollama" in body
    assert "report_v1.md" in body


def test_sessions_route_in_nav(client: TestClient) -> None:
    r = client.get("/")
    body = r.text
    assert 'data-stage="sessions"' in body
    import re

    m = re.search(
        r'data-stage="sessions"\s+data-available="(true|false)"', body
    )
    assert m is not None
    assert m.group(1) == "true"
