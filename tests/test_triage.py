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


def test_get_triage_page_renders(client: TestClient) -> None:
    r = client.get("/triage")
    assert r.status_code == 200
    body = r.text
    assert "Triage" in body
    assert 'name="target"' in body
    assert 'name="snippets"' in body
    assert "What to paste here" in body
    assert "Example snippet block" in body


def test_post_triage_parses_findings_and_sorts_by_priority(
    client: TestClient,
) -> None:
    fake = FakeAdapter(
        json.dumps(
            [
                {
                    "url": "https://example.com/blog/news",
                    "title": "Marketing post",
                    "priority": "low",
                    "why": "static content",
                    "dedup_key": "https://example.com/blog/news",
                },
                {
                    "url": "https://example.com/admin",
                    "title": "Admin panel",
                    "priority": "high",
                    "why": "exposed admin",
                    "dedup_key": "https://example.com/admin",
                },
                {
                    "url": "https://example.com/login",
                    "title": "Login",
                    "priority": "medium",
                    "why": "auth surface",
                    "dedup_key": "https://example.com/login",
                },
            ]
        )
    )
    _override(fake)
    try:
        r = client.post(
            "/triage",
            data={"target": "example.com", "snippets": "Pasted snippets…"},
        )
    finally:
        _restore()
    assert r.status_code == 200
    body = r.text
    # High before medium before low
    high_idx = body.find("/admin")
    med_idx = body.find("/login")
    low_idx = body.find("/blog/news")
    assert 0 <= high_idx < med_idx < low_idx
    # Adapter saw the triage role
    assert len(fake.calls) == 1
    assert fake.calls[0].role == "triage"
    assert fake.calls[0].target == "example.com"
    # finding-count attribute
    m = re.search(r'data-finding-count="(\d+)"', body)
    assert m is not None
    assert int(m.group(1)) == 3


def test_post_triage_dedupes_by_dedup_key(client: TestClient) -> None:
    fake = FakeAdapter(
        json.dumps(
            [
                {
                    "url": "https://example.com/admin",
                    "priority": "high",
                    "why": "first",
                    "dedup_key": "admin-canon",
                },
                {
                    "url": "https://example.com/admin/",
                    "priority": "high",
                    "why": "trailing slash dup",
                    "dedup_key": "admin-canon",
                },
                {
                    "url": "https://example.com/login",
                    "priority": "medium",
                    "why": "fresh",
                    "dedup_key": "login-canon",
                },
            ]
        )
    )
    _override(fake)
    try:
        r = client.post(
            "/triage",
            data={"target": "example.com", "snippets": "x"},
        )
    finally:
        _restore()
    assert r.status_code == 200
    body = r.text
    # 2 findings (1 admin + 1 login), 1 duplicate dropped
    m = re.search(r'data-finding-count="(\d+)"', body)
    assert m and int(m.group(1)) == 2
    m2 = re.search(r'data-duplicates="(\d+)"', body)
    assert m2 and int(m2.group(1)) == 1
    # The visible "X duplicates collapsed" string
    assert "1 duplicate" in body.lower()


def test_post_triage_drops_findings_without_url(client: TestClient) -> None:
    fake = FakeAdapter(
        json.dumps(
            [
                {"priority": "high", "why": "no url"},
                {"url": "https://example.com/admin", "priority": "high"},
            ]
        )
    )
    _override(fake)
    try:
        r = client.post(
            "/triage", data={"target": "example.com", "snippets": "x"}
        )
    finally:
        _restore()
    assert r.status_code == 200
    m = re.search(r'data-finding-count="(\d+)"', r.text)
    assert m and int(m.group(1)) == 1


def test_post_triage_unknown_priority_normalized_to_low(
    client: TestClient,
) -> None:
    fake = FakeAdapter(
        json.dumps(
            [
                {
                    "url": "https://example.com/x",
                    "priority": "CRITICAL!!!",
                    "why": "ignored priority",
                }
            ]
        )
    )
    _override(fake)
    try:
        r = client.post(
            "/triage", data={"target": "example.com", "snippets": "x"}
        )
    finally:
        _restore()
    assert r.status_code == 200
    assert 'data-priority="low"' in r.text


def test_post_triage_model_says_out_of_scope_returns_422(
    client: TestClient,
) -> None:
    fake = FakeAdapter("OUT_OF_SCOPE")
    _override(fake)
    try:
        r = client.post(
            "/triage", data={"target": "example.com", "snippets": "x"}
        )
    finally:
        _restore()
    assert r.status_code == 422
    assert "out of scope" in r.text.lower()


def test_post_triage_non_json_output_shows_unparsed(client: TestClient) -> None:
    fake = FakeAdapter("just some prose, not JSON")
    _override(fake)
    try:
        r = client.post(
            "/triage", data={"target": "example.com", "snippets": "x"}
        )
    finally:
        _restore()
    assert r.status_code == 200
    body = r.text
    assert 'data-state="unparsed"' in body


def test_post_triage_out_of_scope_target_returns_403(client: TestClient) -> None:
    fake = FakeAdapter(
        raises=OutOfScopeError("target out of scope: 'evil.com'")
    )
    _override(fake)
    try:
        r = client.post(
            "/triage", data={"target": "evil.com", "snippets": "x"}
        )
    finally:
        _restore()
    assert r.status_code == 403


def test_post_triage_ai_backend_down_returns_503(client: TestClient) -> None:
    fake = FakeAdapter(
        raises=AIAdapterError(AIErrorReason.NO_BACKEND_AVAILABLE, "down")
    )
    _override(fake)
    try:
        r = client.post(
            "/triage", data={"target": "example.com", "snippets": "x"}
        )
    finally:
        _restore()
    assert r.status_code == 503


def test_post_triage_missing_inputs_returns_400(client: TestClient) -> None:
    r = client.post("/triage", data={"target": "", "snippets": ""})
    assert r.status_code == 400
    assert "missing input" in r.text.lower()


def test_triage_route_now_in_nav(client: TestClient) -> None:
    r = client.get("/")
    body = r.text
    assert 'data-stage="triage"' in body
    m = re.search(
        r'data-stage="triage"\s+data-available="(true|false)"', body
    )
    assert m is not None
    assert m.group(1) == "true"
