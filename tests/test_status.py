import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.core.events import (
    KIND_GROQ_CHECK,
    KIND_OLLAMA_CHECK,
    KIND_PROMPTS_CHECK,
    KIND_REGISTRY_LOADED,
    KIND_SCOPE_LOADED,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARN,
    record,
)
from app.core.status import (
    OVERALL_DEGRADED,
    OVERALL_MISSING,
    OVERALL_OK,
    compute_snapshot,
)


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/")
    def home() -> str:
        return "h"

    return app


@pytest.fixture
def events_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("EVENTS_FILE", str(path))
    return path


def test_snapshot_missing_when_no_events(events_file: Path) -> None:
    snap = compute_snapshot(_app())
    assert snap.overall == OVERALL_MISSING
    assert snap.ollama is None
    assert snap.ollama_models is None
    assert snap.groq is None
    assert snap.registry is None
    assert snap.scope is None
    assert snap.prompts is None


def test_snapshot_ok_when_all_info(events_file: Path) -> None:
    record(KIND_OLLAMA_CHECK, "ollama", "reachable", level=LEVEL_INFO)
    record(KIND_GROQ_CHECK, "groq", "configured", level=LEVEL_INFO)
    record(KIND_REGISTRY_LOADED, "registry", "loaded", level=LEVEL_INFO)
    record(KIND_SCOPE_LOADED, "scope", "loaded", level=LEVEL_INFO)
    record(KIND_PROMPTS_CHECK, "prompts", "3 files", level=LEVEL_INFO)
    snap = compute_snapshot(_app())
    assert snap.overall == OVERALL_OK
    assert snap.ollama is not None
    assert snap.ollama.summary == "reachable"


def test_snapshot_degraded_when_warn(events_file: Path) -> None:
    record(KIND_OLLAMA_CHECK, "ollama", "down", level=LEVEL_WARN)
    record(KIND_GROQ_CHECK, "groq", "configured", level=LEVEL_INFO)
    snap = compute_snapshot(_app())
    assert snap.overall == OVERALL_DEGRADED


def test_snapshot_degraded_when_error(events_file: Path) -> None:
    record(KIND_REGISTRY_LOADED, "registry", "load failed", level=LEVEL_ERROR)
    snap = compute_snapshot(_app())
    assert snap.overall == OVERALL_DEGRADED


def test_snapshot_uses_latest_event_per_kind(events_file: Path) -> None:
    record(KIND_OLLAMA_CHECK, "ollama", "old: down", level=LEVEL_WARN)
    record(KIND_OLLAMA_CHECK, "ollama", "now: reachable", level=LEVEL_INFO)
    snap = compute_snapshot(_app())
    assert snap.ollama is not None
    assert snap.ollama.summary == "now: reachable"
    assert snap.ollama.level == LEVEL_INFO


def test_snapshot_carries_menu_from_capabilities(events_file: Path) -> None:
    snap = compute_snapshot(_app())
    by_id = {m["id"]: m for m in snap.menu}
    assert "home" in by_id
    assert "status" in by_id
    assert "diagnostics" in by_id
    # /status route is NOT mounted in the bare FastAPI test instance.
    assert by_id["status"]["available"] is False


def test_snapshot_does_not_leak_groq_key(
    events_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Even when the groq event records "configured", the API key value must
    # not appear in any field. The probe_groq() helper enforces this; here
    # we verify the snapshot doesn't accidentally widen the surface.
    record(
        KIND_GROQ_CHECK,
        "groq",
        "groq fallback configured (key present)",
        level=LEVEL_INFO,
        configured=True,
        model="llama-3.3-70b-versatile",
    )
    snap = compute_snapshot(_app())
    assert snap.groq is not None
    serialized = json.dumps(
        {
            "summary": snap.groq.summary,
            "data": snap.groq.data,
        }
    )
    assert "GROQ_API_KEY" not in serialized
    # No key value should be embedded — confirm via a sentinel
    monkeypatch.setenv("GROQ_API_KEY", "sk-sentinel-must-not-leak")
    snap2 = compute_snapshot(_app())
    assert "sk-sentinel-must-not-leak" not in json.dumps(
        {"summary": snap2.groq.summary, "data": snap2.groq.data}
    )
