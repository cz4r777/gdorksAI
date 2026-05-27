import json
from pathlib import Path

import httpx
import pytest

from app.core.ai import (
    AIAdapter,
    AIAdapterError,
    AIErrorReason,
    AIRequest,
    _extract_hostnames,
)
from app.core.scope import OutOfScopeError, ScopeGuard

_PROMPT = (
    "---SYSTEM---\n"
    "You are assisting target {target}.\n"
    "---USER---\n"
    "{user_input}\n"
)


def _scope(tmp_path: Path, targets: list[str]) -> ScopeGuard:
    sf = tmp_path / "scope.json"
    sf.write_text(json.dumps({"targets": targets}), encoding="utf-8")
    return ScopeGuard(sf)


def _prompts_dir(tmp_path: Path) -> Path:
    pdir = tmp_path / "prompts"
    pdir.mkdir()
    (pdir / "query_gen_v1.md").write_text(_PROMPT, encoding="utf-8")
    return pdir


def _adapter(
    tmp_path: Path,
    handler: httpx.MockTransport,
    *,
    targets: list[str] | None = None,
    groq_key: str | None = None,
) -> AIAdapter:
    return AIAdapter(
        ollama_host="http://ollama-mock",
        ollama_models={"query_gen": "test-model"},
        groq_api_key=groq_key,
        groq_model="groq-test-model",
        prompts_dir=_prompts_dir(tmp_path),
        scope_guard=_scope(tmp_path, targets or ["example.com"]),
        http_client=httpx.AsyncClient(transport=handler),
    )


def _req(user_input: str = "find exposed configs") -> AIRequest:
    return AIRequest(
        role="query_gen", target="example.com", user_input=user_input
    )


@pytest.fixture(autouse=True)
def _isolate_events(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the events file at a per-test tmp path so emissions can be asserted."""
    target = tmp_path / "events.jsonl"
    monkeypatch.setenv("EVENTS_FILE", str(target))
    return target


def _read_events() -> list[dict]:
    from app.core.events import read_recent

    return [
        {
            "kind": e.kind,
            "level": e.level,
            "component": e.component,
            "summary": e.summary,
            "data": e.data,
        }
        for e in read_recent(50)
    ]


@pytest.mark.asyncio
async def test_ollama_happy_path(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert "example.com" in body["system"]
        assert "find exposed configs" in body["prompt"]
        return httpx.Response(
            200,
            json={"response": 'site:example.com inurl:config'},
        )

    adapter = _adapter(tmp_path, httpx.MockTransport(handler))
    resp = await adapter.generate(_req())
    assert resp.backend == "ollama"
    assert "example.com" in resp.text
    assert resp.role == "query_gen"
    assert resp.prompt_filename == "query_gen_v1.md"
    assert len(resp.prompt_hash) == 64
    # ai_call event emitted on success
    events = _read_events()
    ai_calls = [e for e in events if e["kind"] == "ai_call"]
    assert len(ai_calls) == 1
    assert ai_calls[0]["data"]["role"] == "query_gen"
    assert ai_calls[0]["data"]["backend"] == "ollama"
    # Metadata-only invariant: target MUST NOT appear in the event payload.
    assert "target" not in ai_calls[0]["data"]
    await adapter.aclose()


@pytest.mark.asyncio
async def test_scope_rejects_before_backend_call(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"response": "site:example.com"})

    adapter = _adapter(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(OutOfScopeError):
        await adapter.generate(
            AIRequest(role="query_gen", target="victim.com", user_input="x")
        )
    assert calls == []
    # ai_refused event emitted on scope rejection
    events = _read_events()
    refused = [e for e in events if e["kind"] == "ai_refused"]
    assert len(refused) == 1
    assert refused[0]["data"]["reason"] == "out_of_scope_target"
    # Metadata-only invariant: target MUST NOT appear in the event payload.
    assert "target" not in refused[0]["data"]
    assert refused[0]["level"] == "warn"
    await adapter.aclose()


@pytest.mark.asyncio
async def test_ollama_unreachable_falls_back_to_groq(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "ollama-mock" in str(request.url):
            raise httpx.ConnectError("connection refused")
        # groq
        assert request.headers.get("authorization") == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "site:example.com inurl:.env"}}
                ]
            },
        )

    adapter = _adapter(
        tmp_path, httpx.MockTransport(handler), groq_key="test-key"
    )
    resp = await adapter.generate(_req())
    assert resp.backend == "groq"
    assert "example.com" in resp.text
    await adapter.aclose()


@pytest.mark.asyncio
async def test_ollama_unreachable_without_groq_raises_no_backend(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    adapter = _adapter(tmp_path, httpx.MockTransport(handler), groq_key=None)
    with pytest.raises(AIAdapterError) as ei:
        await adapter.generate(_req())
    assert ei.value.reason == AIErrorReason.NO_BACKEND_AVAILABLE
    await adapter.aclose()


@pytest.mark.asyncio
async def test_ollama_model_missing_falls_back_to_groq(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "ollama-mock" in str(request.url):
            return httpx.Response(404, json={"error": "model not found"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "site:example.com filetype:env"}}
                ]
            },
        )

    adapter = _adapter(
        tmp_path, httpx.MockTransport(handler), groq_key="test-key"
    )
    resp = await adapter.generate(_req())
    assert resp.backend == "groq"
    await adapter.aclose()


@pytest.mark.asyncio
async def test_groq_rate_limited_surfaces_typed_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "ollama-mock" in str(request.url):
            raise httpx.ConnectError("down")
        return httpx.Response(429, json={"error": "rate limited"})

    adapter = _adapter(
        tmp_path, httpx.MockTransport(handler), groq_key="test-key"
    )
    with pytest.raises(AIAdapterError) as ei:
        await adapter.generate(_req())
    assert ei.value.reason == AIErrorReason.GROQ_RATE_LIMITED
    await adapter.aclose()


@pytest.mark.asyncio
async def test_post_call_out_of_scope_output_refused(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Model leaks a different domain
        return httpx.Response(
            200,
            json={"response": "try site:other-target.net inurl:admin"},
        )

    adapter = _adapter(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(AIAdapterError) as ei:
        await adapter.generate(_req())
    assert ei.value.reason == AIErrorReason.OUT_OF_SCOPE_OUTPUT
    # ai_refused event emitted on post-call refusal
    events = _read_events()
    refused = [e for e in events if e["kind"] == "ai_refused"]
    assert len(refused) == 1
    assert refused[0]["data"]["reason"] == "out_of_scope_output"
    assert refused[0]["data"]["backend"] == "ollama"
    await adapter.aclose()


@pytest.mark.asyncio
async def test_post_call_allows_in_scope_subdomain_when_scope_has_wildcard(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"response": "site:api.example.com inurl:swagger"},
        )

    adapter = _adapter(
        tmp_path,
        httpx.MockTransport(handler),
        targets=["example.com", "*.example.com"],
    )
    resp = await adapter.generate(_req())
    assert "api.example.com" in resp.text
    await adapter.aclose()


@pytest.mark.asyncio
async def test_ollama_returns_non_json_raises_malformed(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    adapter = _adapter(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(AIAdapterError) as ei:
        await adapter.generate(_req())
    assert ei.value.reason == AIErrorReason.MALFORMED_RESPONSE
    await adapter.aclose()


@pytest.mark.asyncio
async def test_unknown_role_raises_prompt_not_found(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "site:example.com"})

    adapter = _adapter(tmp_path, httpx.MockTransport(handler))
    with pytest.raises(AIAdapterError) as ei:
        await adapter.generate(
            AIRequest(role="nope", target="example.com", user_input="x")
        )
    assert ei.value.reason == AIErrorReason.PROMPT_NOT_FOUND
    await adapter.aclose()


@pytest.mark.asyncio
async def test_groq_5xx_surfaces_http_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "ollama-mock" in str(request.url):
            raise httpx.ConnectError("down")
        return httpx.Response(500, json={"error": "boom"})

    adapter = _adapter(
        tmp_path, httpx.MockTransport(handler), groq_key="test-key"
    )
    with pytest.raises(AIAdapterError) as ei:
        await adapter.generate(_req())
    assert ei.value.reason == AIErrorReason.GROQ_HTTP_ERROR
    await adapter.aclose()


def test_extract_hostnames_finds_plausible_domains() -> None:
    text = "try site:example.com or site:api.example.com or 'foo bar' or 1.2.3.4 or example."
    hosts = _extract_hostnames(text)
    assert "example.com" in hosts
    assert "api.example.com" in hosts
    # IP is not matched as a hostname pattern (no alpha TLD)
    assert "1.2.3.4" not in hosts


@pytest.mark.asyncio
async def test_logs_prompt_filename_and_hash_on_success(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "site:example.com"})

    adapter = _adapter(tmp_path, httpx.MockTransport(handler))
    with caplog.at_level(logging.INFO, logger="gdorksai.ai"):
        resp = await adapter.generate(_req())
    assert any(
        "query_gen_v1.md" in rec.message and resp.prompt_hash[:12] in rec.message
        for rec in caplog.records
    )
    await adapter.aclose()
