import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from app.core import events as events_mod
from app.core import health
from app.core.events import (
    KIND_GROQ_CHECK,
    KIND_HEALTH_CHECK,
    KIND_OLLAMA_CHECK,
    KIND_PROMPTS_CHECK,
    KIND_REGISTRY_LOADED,
    KIND_SCOPE_LOADED,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARN,
    read_recent,
)
from app.core.scope import reset_default_guard


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("EVENTS_FILE", str(tmp_path / "events.jsonl"))
    reset_default_guard()
    return tmp_path


def _stub_async_client(handler: httpx.MockTransport):
    real_init = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = handler
        real_init(self, *args, **kwargs)

    return patch.object(httpx.AsyncClient, "__init__", patched)


@pytest.mark.asyncio
async def test_probe_ollama_reachable(env: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": []})

    with _stub_async_client(httpx.MockTransport(handler)):
        e = await health.probe_ollama()
    assert e.kind == KIND_OLLAMA_CHECK
    assert e.level == LEVEL_INFO
    assert e.data["reachable"] is True


@pytest.mark.asyncio
async def test_probe_ollama_connection_error(env: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    with _stub_async_client(httpx.MockTransport(handler)):
        e = await health.probe_ollama()
    assert e.level == LEVEL_WARN
    assert e.data["reachable"] is False
    assert e.data["detail"] == "ConnectError"


@pytest.mark.asyncio
async def test_probe_ollama_non_200(env: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    with _stub_async_client(httpx.MockTransport(handler)):
        e = await health.probe_ollama()
    assert e.level == LEVEL_WARN
    assert e.data["reachable"] is False


def test_probe_groq_unconfigured(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    e = health.probe_groq()
    assert e.kind == KIND_GROQ_CHECK
    assert e.level == LEVEL_INFO
    assert e.data["configured"] is False


def test_probe_groq_configured_does_not_call_out(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    e = health.probe_groq()
    assert e.data["configured"] is True
    # Key is not echoed back into the event
    assert "test-key" not in json.dumps(e.data)


def test_probe_registry_loaded(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    cat = corpus / "SQLi"
    cat.mkdir()
    (cat / "basic.txt").write_text("site:{target} inurl:id=\n", encoding="utf-8")
    monkeypatch.setenv("DORKS_DATA_PATH", str(corpus))
    # Reset the registry singleton from the web module so the probe sees the new env
    from app import web

    web.reset_registry()
    e = health.probe_registry()
    assert e.kind == KIND_REGISTRY_LOADED
    assert e.data["dork_count"] >= 1
    assert e.data["category_count"] >= 1


def test_probe_registry_empty_path_warns(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("DORKS_DATA_PATH", str(empty))
    from app import web

    web.reset_registry()
    e = health.probe_registry()
    assert e.level == LEVEL_WARN
    assert e.data["dork_count"] == 0


def test_probe_scope_missing_file_warns(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SCOPE_FILE", str(tmp_path / "absent.json"))
    reset_default_guard()
    e = health.probe_scope()
    assert e.kind == KIND_SCOPE_LOADED
    assert e.level == LEVEL_WARN
    assert e.data["file_exists"] is False


def test_probe_scope_loaded(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"targets": ["example.com", "*.example.com"]}), encoding="utf-8")
    monkeypatch.setenv("SCOPE_FILE", str(scope))
    reset_default_guard()
    e = health.probe_scope()
    assert e.level == LEVEL_INFO
    assert e.data["target_count"] == 2
    assert e.data["exact_count"] == 1
    assert e.data["wildcard_count"] == 1


def test_probe_prompts_missing_dir(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PROMPTS_DIR", str(tmp_path / "nope"))
    e = health.probe_prompts()
    assert e.kind == KIND_PROMPTS_CHECK
    assert e.level == LEVEL_WARN
    assert e.data["count"] == 0


def test_probe_prompts_present(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pdir = tmp_path / "prompts"
    pdir.mkdir()
    (pdir / "query_gen_v1.md").write_text("p", encoding="utf-8")
    (pdir / "triage_v2.md").write_text("p", encoding="utf-8")
    monkeypatch.setenv("PROMPTS_DIR", str(pdir))
    e = health.probe_prompts()
    assert e.level == LEVEL_INFO
    assert e.data["count"] == 2


@pytest.mark.asyncio
async def test_run_health_checks_emits_one_event_per_probe_plus_summary(
    env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Make ollama reachable so the summary is INFO.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    # Configure a valid scope + corpus to keep everything green.
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"targets": ["example.com"]}), encoding="utf-8")
    monkeypatch.setenv("SCOPE_FILE", str(scope))
    reset_default_guard()

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    cat = corpus / "SQLi"
    cat.mkdir()
    (cat / "basic.txt").write_text("site:{target} inurl:id=\n", encoding="utf-8")
    monkeypatch.setenv("DORKS_DATA_PATH", str(corpus))
    from app import web

    web.reset_registry()

    pdir = tmp_path / "prompts"
    pdir.mkdir()
    (pdir / "query_gen_v1.md").write_text("p", encoding="utf-8")
    monkeypatch.setenv("PROMPTS_DIR", str(pdir))

    with _stub_async_client(httpx.MockTransport(handler)):
        events = await health.run_health_checks()

    kinds = [e.kind for e in events]
    assert kinds == [
        KIND_OLLAMA_CHECK,
        KIND_GROQ_CHECK,
        KIND_REGISTRY_LOADED,
        KIND_SCOPE_LOADED,
        KIND_PROMPTS_CHECK,
        KIND_HEALTH_CHECK,
    ]
    summary = events[-1]
    assert summary.level == LEVEL_INFO
    assert summary.data["counts"][LEVEL_INFO] >= 1
    # And all of them are persisted to the events file.
    written = read_recent(20)
    assert len(written) == len(events)
