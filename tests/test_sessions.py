import json
from pathlib import Path

import pytest

from app.core import events as events_mod
from app.core.sessions import save_report, sessions_dir


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("EVENTS_FILE", str(tmp_path / "events.jsonl"))


def test_sessions_dir_honors_env(tmp_path: Path) -> None:
    assert sessions_dir() == tmp_path / "sessions"


def test_save_report_writes_md_and_meta(tmp_path: Path) -> None:
    saved = save_report(
        target="example.com",
        markdown="## Summary\n\nShort.",
        backend="ollama",
        prompt_filename="report_v1.md",
        prompt_hash="a" * 64,
    )
    assert saved.session_id
    assert saved.directory.is_dir()
    assert saved.report_path.read_text(encoding="utf-8") == "## Summary\n\nShort."
    meta = json.loads(saved.meta_path.read_text(encoding="utf-8"))
    assert meta["target"] == "example.com"
    assert meta["backend"] == "ollama"
    assert meta["prompt_filename"] == "report_v1.md"
    assert meta["prompt_hash"] == "a" * 64
    assert meta["session_id"] == saved.session_id
    assert meta["ts"].endswith("+00:00")


def test_save_report_emits_session_saved_event(tmp_path: Path) -> None:
    saved = save_report(
        target="example.com",
        markdown="x",
        backend="groq",
        prompt_filename="report_v1.md",
        prompt_hash="b" * 64,
    )
    events = events_mod.read_recent(10)
    matched = [e for e in events if e.kind == "session_saved"]
    assert len(matched) == 1
    e = matched[0]
    assert e.data["session_id"] == saved.session_id
    assert e.data["target"] == "example.com"
    assert e.data["backend"] == "groq"
    assert e.data["prompt_hash_prefix"] == "b" * 12
    # No raw prompt hash leak — only first 12 chars
    assert "b" * 64 not in json.dumps(e.data)


def test_save_report_session_ids_unique(tmp_path: Path) -> None:
    seen: set[str] = set()
    for _ in range(5):
        saved = save_report(
            target="example.com",
            markdown="x",
            backend="ollama",
            prompt_filename="report_v1.md",
            prompt_hash="c" * 64,
        )
        assert saved.session_id not in seen
        seen.add(saved.session_id)
