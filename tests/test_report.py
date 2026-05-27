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
    monkeypatch.setenv("EVENTS_FILE", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
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


def test_get_report_page_renders(client: TestClient) -> None:
    r = client.get("/report")
    assert r.status_code == 200
    body = r.text
    assert "Report" in body
    assert 'name="target"' in body
    assert 'name="session_log"' in body
    assert "What makes a good report input" in body
    assert "Example session log" in body
    assert "/sessions" in body


def test_post_report_returns_markdown_partial(client: TestClient) -> None:
    fake = FakeAdapter(
        "## Summary\n\nShort engagement summary for example.com.\n\n"
        "## Findings\n\n- **[high]** *config-leaks* — env exposed — "
        "`https://example.com/.env`\n\n## Recommendations\n\n- Rotate\n\n"
        "## Methodology\n\nUsed dork categories: config-leaks."
    )
    _override(fake)
    try:
        r = client.post(
            "/report",
            data={
                "target": "example.com",
                "session_log": "found env file at /.env",
            },
        )
    finally:
        _restore()
    assert r.status_code == 200
    body = r.text
    assert "## Summary" in body
    assert "config-leaks" in body
    assert 'data-state="report-ready"' in body
    assert 'data-backend="fake"' in body
    # No <html wrapper — it's a partial
    assert "<html" not in body.lower()
    assert len(fake.calls) == 1
    assert fake.calls[0].role == "report"
    assert fake.calls[0].target == "example.com"


def test_post_report_model_says_out_of_scope_returns_422(
    client: TestClient,
) -> None:
    fake = FakeAdapter("OUT_OF_SCOPE")
    _override(fake)
    try:
        r = client.post(
            "/report",
            data={"target": "example.com", "session_log": "off-target"},
        )
    finally:
        _restore()
    assert r.status_code == 422
    assert "out of scope" in r.text.lower()


def test_post_report_out_of_scope_target_returns_403(client: TestClient) -> None:
    fake = FakeAdapter(
        raises=OutOfScopeError("target out of scope: 'evil.com'")
    )
    _override(fake)
    try:
        r = client.post(
            "/report", data={"target": "evil.com", "session_log": "x"}
        )
    finally:
        _restore()
    assert r.status_code == 403


def test_post_report_ai_backend_down_returns_503(client: TestClient) -> None:
    fake = FakeAdapter(
        raises=AIAdapterError(AIErrorReason.NO_BACKEND_AVAILABLE, "down")
    )
    _override(fake)
    try:
        r = client.post(
            "/report", data={"target": "example.com", "session_log": "x"}
        )
    finally:
        _restore()
    assert r.status_code == 503


def test_post_report_missing_inputs_returns_400(client: TestClient) -> None:
    r = client.post("/report", data={"target": "", "session_log": ""})
    assert r.status_code == 400


def test_post_report_persists_session_to_disk(
    client: TestClient, tmp_path: Path
) -> None:
    fake = FakeAdapter(
        "## Summary\n\nFinding on example.com.\n\n## Findings\n\n- one\n\n"
        "## Recommendations\n\n- rotate\n\n## Methodology\n\nDorks."
    )
    _override(fake)
    try:
        r = client.post(
            "/report",
            data={"target": "example.com", "session_log": "log"},
        )
    finally:
        _restore()
    assert r.status_code == 200
    body = r.text
    # Session id surfaces in the response partial
    import re

    m = re.search(r'data-session-id="([^"]+)"', body)
    assert m is not None
    session_id = m.group(1)
    sessions_root = tmp_path / "sessions"
    session_dir = sessions_root / session_id
    assert session_dir.is_dir()
    report_md = (session_dir / "report.md").read_text(encoding="utf-8")
    assert "## Summary" in report_md
    meta = json.loads(
        (session_dir / "meta.json").read_text(encoding="utf-8")
    )
    assert meta["target"] == "example.com"
    assert meta["backend"] == "fake"


def test_report_route_now_in_nav(client: TestClient) -> None:
    r = client.get("/")
    body = r.text
    assert 'data-stage="report"' in body
    m = re.search(
        r'data-stage="report"\s+data-available="(true|false)"', body
    )
    assert m is not None
    assert m.group(1) == "true"
