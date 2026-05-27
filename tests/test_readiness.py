import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from app.core import scope as scope_module
from app.core.readiness import _ready_for_ai, run_startup_readiness


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVENTS_FILE", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    scope_module.reset_default_guard()


def _stub_async_client(handler: httpx.MockTransport):
    real_init = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = handler
        real_init(self, *args, **kwargs)

    return patch.object(httpx.AsyncClient, "__init__", patched)


def _ok_ollama(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, json={"models": [{"name": "llama3.1:8b-instruct"}]}
    )


@pytest.mark.asyncio
async def test_run_startup_readiness_all_green(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Configure scope, corpus, prompts so the cheap probes pass
    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps({"targets": ["example.com"]}), encoding="utf-8"
    )
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "SQLi").mkdir()
    (corpus / "SQLi" / "basic.txt").write_text(
        "site:{target}\n", encoding="utf-8"
    )
    pdir = tmp_path / "prompts"
    pdir.mkdir()
    (pdir / "query_gen_v1.md").write_text("p", encoding="utf-8")
    monkeypatch.setenv("SCOPE_FILE", str(scope))
    monkeypatch.setenv("DORKS_DATA_PATH", str(corpus))
    monkeypatch.setenv("PROMPTS_DIR", str(pdir))
    monkeypatch.setenv("OLLAMA_MODEL_QUERY", "llama3.1:8b-instruct")
    from app import web

    web.reset_registry()
    scope_module.reset_default_guard()
    with _stub_async_client(httpx.MockTransport(_ok_ollama)):
        ev = await run_startup_readiness()
    assert ev.kind == "startup_readiness"
    assert ev.level == "info"
    assert ev.data["ready_for_ai"] is True
    assert ev.data["counts"]["info"] >= 5


@pytest.mark.asyncio
async def test_run_startup_readiness_warn_when_missing_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SCOPE_FILE", str(tmp_path / "absent.json"))
    monkeypatch.setenv("DORKS_DATA_PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("PROMPTS_DIR", str(tmp_path / "no_prompts"))
    from app import web

    web.reset_registry()
    scope_module.reset_default_guard()
    with _stub_async_client(httpx.MockTransport(_ok_ollama)):
        ev = await run_startup_readiness()
    assert ev.level == "warn"
    # ready_for_ai requires ollama models present; OLLAMA_MODEL_QUERY isn't
    # set in this test, so by_role is empty and missing is empty too —
    # that's the "no configured models" case which means not-ready.
    # We allow either; the key signal is that level=warn.


@pytest.mark.asyncio
async def test_ready_for_ai_groq_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Groq alone (no ollama) still counts as ready_for_ai."""
    monkeypatch.setenv(
        "SCOPE_FILE",
        str(_make_scope(tmp_path)),
    )
    monkeypatch.setenv("GROQ_API_KEY", "sk-test")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("ollama down")

    from app import web

    web.reset_registry()
    scope_module.reset_default_guard()
    with _stub_async_client(httpx.MockTransport(handler)):
        ev = await run_startup_readiness()
    assert ev.data["ready_for_ai"] is True


def _make_scope(tmp_path: Path) -> Path:
    f = tmp_path / "scope.json"
    f.write_text(json.dumps({"targets": ["example.com"]}), encoding="utf-8")
    return f


def test_ready_for_ai_helper_neither() -> None:
    # No ollama, no groq -> not ready
    assert _ready_for_ai([]) is False
