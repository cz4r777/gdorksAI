import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import web
from app.core import scope as scope_module
from app.core.ai import (
    AIAdapterError,
    AIErrorReason,
    AIRequest,
    AIResponse,
)
from app.core.scope import OutOfScopeError
from app.main import app


class FakeAdapter:
    """Records calls + returns canned text. Used via app.dependency_overrides."""

    def __init__(
        self,
        response_text: str = "",
        raises: Exception | None = None,
    ) -> None:
        self.response_text = response_text
        self.raises = raises
        self.calls: list[AIRequest] = []

    async def generate(self, req: AIRequest) -> AIResponse:
        self.calls.append(req)
        if self.raises is not None:
            raise self.raises
        return AIResponse(
            text=self.response_text,
            backend="fake",
            role=req.role,
            target=req.target,
            prompt_filename="fake_v1.md",
            prompt_hash="deadbeef" * 8,
        )

    async def aclose(self) -> None:
        pass


def _seed_corpus(root: Path) -> None:
    cat = root / "SQLi"
    cat.mkdir()
    (cat / "basic.txt").write_text("site:{target} inurl:id=\n", encoding="utf-8")


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> TestClient:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _seed_corpus(corpus)
    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps({"targets": ["example.com"]}), encoding="utf-8"
    )
    monkeypatch.setenv("DORKS_DATA_PATH", str(corpus))
    monkeypatch.setenv("SCOPE_FILE", str(scope))
    web.reset_registry()
    web.reset_adapter()
    scope_module.reset_default_guard()
    return TestClient(app)


def _override(adapter: FakeAdapter) -> None:
    app.dependency_overrides[web.get_adapter] = lambda: adapter


def _restore() -> None:
    app.dependency_overrides.clear()


def test_get_query_page_renders(client: TestClient) -> None:
    r = client.get("/query")
    assert r.status_code == 200
    body = r.text
    assert "Query" in body
    assert 'name="target"' in body
    assert 'name="intent"' in body
    assert 'hx-post="/query"' in body
    assert "How to use this page" in body
    assert "Good example prompts" in body
    assert "/status" in body


def test_post_query_structured_json(client: TestClient) -> None:
    fake = FakeAdapter(
        '{"dork": "site:example.com inurl:.env", '
        '"category": "config-leaks", '
        '"rationale": "look for environment files"}'
    )
    _override(fake)
    try:
        r = client.post(
            "/query",
            data={"target": "example.com", "intent": "find leaked configs"},
        )
    finally:
        _restore()
    assert r.status_code == 200
    body = r.text
    assert "config-leaks" in body
    assert "look for environment files" in body
    assert "site:example.com inurl:.env" in body
    assert "google.com/search" in body
    assert len(fake.calls) == 1
    assert fake.calls[0].role == "query_gen"
    assert fake.calls[0].target == "example.com"
    assert fake.calls[0].user_input == "find leaked configs"


def test_post_query_substitutes_target_placeholder(client: TestClient) -> None:
    fake = FakeAdapter(
        '{"dork": "site:{target} inurl:admin", '
        '"category": "auth-pages", "rationale": ""}'
    )
    _override(fake)
    try:
        r = client.post(
            "/query",
            data={"target": "example.com", "intent": "find admin"},
        )
    finally:
        _restore()
    assert r.status_code == 200
    # {target} should be replaced with example.com
    assert "site:example.com inurl:admin" in r.text


def test_post_query_substitutes_authorized_target_literal(
    client: TestClient,
) -> None:
    fake = FakeAdapter(
        '{"dork": "site:AUTHORIZED_TARGET inurl:admin", '
        '"category": "auth-pages", "rationale": ""}'
    )
    _override(fake)
    try:
        r = client.post(
            "/query",
            data={"target": "example.com", "intent": "find admin"},
        )
    finally:
        _restore()
    assert r.status_code == 200
    assert "site:example.com inurl:admin" in r.text


def test_post_query_unparseable_output_falls_back_to_raw(
    client: TestClient,
) -> None:
    fake = FakeAdapter("site:example.com inurl:.env (not JSON at all)")
    _override(fake)
    try:
        r = client.post(
            "/query",
            data={"target": "example.com", "intent": "leaked configs"},
        )
    finally:
        _restore()
    assert r.status_code == 200
    body = r.text
    assert "(unparsed)" in body
    assert "site:example.com" in body
    assert 'data-structured="false"' in body


def test_post_query_out_of_scope_returns_403(client: TestClient) -> None:
    fake = FakeAdapter(
        raises=OutOfScopeError("target out of scope: 'evil.com'")
    )
    _override(fake)
    try:
        r = client.post(
            "/query",
            data={"target": "evil.com", "intent": "x"},
        )
    finally:
        _restore()
    assert r.status_code == 403
    assert "out of scope" in r.text.lower()


def test_post_query_ai_unavailable_returns_503(client: TestClient) -> None:
    fake = FakeAdapter(
        raises=AIAdapterError(
            AIErrorReason.NO_BACKEND_AVAILABLE, "all backends down"
        )
    )
    _override(fake)
    try:
        r = client.post(
            "/query",
            data={"target": "example.com", "intent": "x"},
        )
    finally:
        _restore()
    assert r.status_code == 503
    assert "no_backend_available" in r.text


def test_post_query_out_of_scope_output_returns_422(client: TestClient) -> None:
    fake = FakeAdapter(
        raises=AIAdapterError(
            AIErrorReason.OUT_OF_SCOPE_OUTPUT, "model leaked another host"
        )
    )
    _override(fake)
    try:
        r = client.post(
            "/query",
            data={"target": "example.com", "intent": "x"},
        )
    finally:
        _restore()
    assert r.status_code == 422


def test_post_query_groq_rate_limited_returns_429(client: TestClient) -> None:
    fake = FakeAdapter(
        raises=AIAdapterError(AIErrorReason.GROQ_RATE_LIMITED, "429")
    )
    _override(fake)
    try:
        r = client.post(
            "/query",
            data={"target": "example.com", "intent": "x"},
        )
    finally:
        _restore()
    assert r.status_code == 429


def test_post_query_missing_input_returns_400(client: TestClient) -> None:
    r = client.post("/query", data={"target": "", "intent": ""})
    assert r.status_code == 400
    assert "missing input" in r.text.lower()


def test_query_route_now_in_nav(client: TestClient) -> None:
    r = client.get("/")
    body = r.text
    assert 'data-stage="query"' in body
    m = re.search(
        r'data-stage="query"\s+data-available="(true|false)"', body
    )
    assert m is not None
    assert m.group(1) == "true"
