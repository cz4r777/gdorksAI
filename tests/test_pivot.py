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
            prompt_hash="d" * 64,
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
    c = TestClient(app)
    c.headers["HX-Request"] = "true"
    return c


def _override(adapter: FakeAdapter) -> None:
    app.dependency_overrides[web.get_adapter] = lambda: adapter


def _restore() -> None:
    app.dependency_overrides.clear()


def test_get_pivot_page_renders(client: TestClient) -> None:
    r = client.get("/pivot")
    assert r.status_code == 200
    body = r.text
    assert "Pivot" in body
    assert 'name="target"' in body
    assert 'name="finding"' in body


def test_post_pivot_parses_multiple_json_lines(client: TestClient) -> None:
    fake = FakeAdapter(
        "\n".join(
            [
                '{"dork": "site:example.com inurl:backup", '
                '"category": "config-leaks", '
                '"rationale": "sibling backup files often near config"}',
                '{"dork": "site:example.com inurl:.sql", '
                '"category": "exposed-files", '
                '"rationale": "exported SQL dumps next to admin"}',
                '{"dork": "site:example.com filetype:env", '
                '"category": "config-leaks", '
                '"rationale": "env files commonly co-located"}',
            ]
        )
    )
    _override(fake)
    try:
        r = client.post(
            "/pivot",
            data={
                "target": "example.com",
                "finding": "https://example.com/admin",
            },
        )
    finally:
        _restore()
    assert r.status_code == 200
    body = r.text
    assert "inurl:backup" in body
    assert "inurl:.sql" in body
    assert "filetype:env" in body
    # Adapter saw the pivot role
    assert len(fake.calls) == 1
    assert fake.calls[0].role == "pivot"
    assert fake.calls[0].target == "example.com"
    assert "https://example.com/admin" in fake.calls[0].user_input


def test_post_pivot_substitutes_target_placeholder(client: TestClient) -> None:
    fake = FakeAdapter(
        '{"dork": "site:{target} inurl:debug", '
        '"category": "version-disclosure", '
        '"rationale": "debug paths fingerprint stack"}'
    )
    _override(fake)
    try:
        r = client.post(
            "/pivot",
            data={"target": "example.com", "finding": "exposed admin"},
        )
    finally:
        _restore()
    assert r.status_code == 200
    assert "site:example.com inurl:debug" in r.text


def test_post_pivot_model_says_out_of_scope_returns_422(
    client: TestClient,
) -> None:
    fake = FakeAdapter("OUT_OF_SCOPE")
    _override(fake)
    try:
        r = client.post(
            "/pivot",
            data={
                "target": "example.com",
                "finding": "https://other.tld/admin",
            },
        )
    finally:
        _restore()
    assert r.status_code == 422
    assert "out of scope" in r.text.lower()


def test_post_pivot_out_of_scope_target_returns_403(client: TestClient) -> None:
    fake = FakeAdapter(
        raises=OutOfScopeError("target out of scope: 'evil.com'")
    )
    _override(fake)
    try:
        r = client.post(
            "/pivot",
            data={"target": "evil.com", "finding": "anything"},
        )
    finally:
        _restore()
    assert r.status_code == 403


def test_post_pivot_ai_backend_down_returns_503(client: TestClient) -> None:
    fake = FakeAdapter(
        raises=AIAdapterError(AIErrorReason.NO_BACKEND_AVAILABLE, "down")
    )
    _override(fake)
    try:
        r = client.post(
            "/pivot",
            data={"target": "example.com", "finding": "x"},
        )
    finally:
        _restore()
    assert r.status_code == 503


def test_post_pivot_groq_rate_limited_returns_429(client: TestClient) -> None:
    fake = FakeAdapter(
        raises=AIAdapterError(AIErrorReason.GROQ_RATE_LIMITED, "429")
    )
    _override(fake)
    try:
        r = client.post(
            "/pivot",
            data={"target": "example.com", "finding": "x"},
        )
    finally:
        _restore()
    assert r.status_code == 429


def test_post_pivot_missing_inputs_returns_400(client: TestClient) -> None:
    r = client.post("/pivot", data={"target": "", "finding": ""})
    assert r.status_code == 400


def test_post_pivot_unparseable_falls_back_to_raw(client: TestClient) -> None:
    fake = FakeAdapter("just some prose, not JSON")
    _override(fake)
    try:
        r = client.post(
            "/pivot",
            data={"target": "example.com", "finding": "x"},
        )
    finally:
        _restore()
    assert r.status_code == 200
    # _parse_query_suggestions falls back to a single raw suggestion
    assert "(unparsed)" in r.text


def test_pivot_route_now_in_nav(client: TestClient) -> None:
    r = client.get("/")
    body = r.text
    assert 'data-stage="pivot"' in body
    m = re.search(
        r'data-stage="pivot"\s+data-available="(true|false)"', body
    )
    assert m is not None
    assert m.group(1) == "true"
