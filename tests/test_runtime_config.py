import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import web
from app.core import scope as scope_module
from app.core.runtime_config import compute_runtime_config
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
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama-test:11434")
    monkeypatch.setenv("OLLAMA_MODEL_QUERY", "test-query-model")
    web.reset_registry()
    scope_module.reset_default_guard()
    return TestClient(app)


def test_compute_runtime_config_reads_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DORKS_DATA_PATH", "/x/dorks")
    monkeypatch.setenv("OLLAMA_HOST", "http://h:1")
    snap = compute_runtime_config()
    paths_by_name = {e.name: e for e in snap.paths}
    backend_by_name = {e.name: e for e in snap.ai_backend}
    assert paths_by_name["DORKS_DATA_PATH"].value == "/x/dorks"
    assert backend_by_name["OLLAMA_HOST"].value == "http://h:1"


def test_groq_key_reported_presence_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "sk-secret-do-not-leak")
    snap = compute_runtime_config()
    groq = next(e for e in snap.ai_backend if e.name == "GROQ_API_KEY")
    assert groq.value == "configured"
    # Sentinel must not appear anywhere in the snapshot
    serialized = json.dumps(
        [
            {"name": e.name, "value": e.value}
            for e in (snap.paths + snap.ai_backend)
        ]
    )
    assert "sk-secret-do-not-leak" not in serialized


def test_groq_not_configured_reports_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    snap = compute_runtime_config()
    groq = next(e for e in snap.ai_backend if e.name == "GROQ_API_KEY")
    assert groq.value == "not configured"


def test_status_page_renders_runtime_config(client: TestClient) -> None:
    r = client.get("/status")
    assert r.status_code == 200
    body = r.text
    assert 'data-testid="runtime-config"' in body
    assert "DORKS_DATA_PATH" in body
    assert "OLLAMA_HOST" in body
    assert "http://ollama-test:11434" in body
    assert "test-query-model" in body


def test_status_page_groq_key_value_not_leaked(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "sk-status-page-test")
    r = client.get("/status")
    assert "sk-status-page-test" not in r.text
    # And the badge says "configured"
    assert "configured" in r.text.lower()
