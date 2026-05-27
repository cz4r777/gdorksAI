import json
from pathlib import Path

import pytest

from app.core import events as events_mod
from app.core.events import (
    KIND_OLLAMA_CHECK,
    LEVEL_INFO,
    LEVEL_WARN,
    events_file,
    read_recent,
    record,
)


@pytest.fixture
def events_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    target = tmp_path / "events.jsonl"
    monkeypatch.setenv("EVENTS_FILE", str(target))
    return target


def test_events_file_honors_env_override(events_path: Path) -> None:
    assert events_file() == events_path


def test_record_appends_one_json_line(events_path: Path) -> None:
    e = record("startup", "app", "hello", level=LEVEL_INFO, version="1.0")
    assert e.kind == "startup"
    assert e.component == "app"
    assert e.summary == "hello"
    assert e.data == {"version": "1.0"}

    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["kind"] == "startup"
    assert obj["level"] == "info"
    assert obj["data"] == {"version": "1.0"}
    assert "ts" in obj and obj["ts"].endswith("+00:00")


def test_multiple_records_append(events_path: Path) -> None:
    record("startup", "app", "a")
    record("startup", "app", "b")
    record("startup", "app", "c")
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_read_recent_returns_oldest_first(events_path: Path) -> None:
    record("startup", "app", "a")
    record("startup", "app", "b")
    record("startup", "app", "c")
    recent = read_recent(10)
    assert [e.summary for e in recent] == ["a", "b", "c"]


def test_read_recent_caps_to_n(events_path: Path) -> None:
    for i in range(5):
        record("startup", "app", f"e{i}")
    recent = read_recent(2)
    assert len(recent) == 2
    assert [e.summary for e in recent] == ["e3", "e4"]


def test_read_recent_missing_file_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("EVENTS_FILE", str(tmp_path / "absent.jsonl"))
    assert read_recent() == []


def test_read_recent_skips_malformed_lines(events_path: Path) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        '{"ts":"x","kind":"k","level":"info","component":"c","summary":"ok","data":{}}\n'
        "not-json-at-all\n"
        '{"ts":"y","kind":"k","level":"warn","component":"c","summary":"two","data":{}}\n',
        encoding="utf-8",
    )
    recent = read_recent()
    assert [e.summary for e in recent] == ["ok", "two"]
    assert recent[1].level == LEVEL_WARN


def test_record_writes_levels(events_path: Path) -> None:
    record(KIND_OLLAMA_CHECK, "ollama", "down", level=LEVEL_WARN, host="h")
    recent = read_recent()
    assert recent[0].level == LEVEL_WARN
    assert recent[0].component == "ollama"
    assert recent[0].data == {"host": "h"}


def test_record_does_not_raise_when_unwritable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Point at a path under a regular file (so mkdir fails).
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("EVENTS_FILE", str(blocker / "events.jsonl"))
    # Must not raise.
    e = record("startup", "app", "still works")
    assert e.summary == "still works"


def test_clear_for_test_removes_file(events_path: Path) -> None:
    record("startup", "app", "x")
    assert events_path.is_file()
    events_mod.clear_for_test()
    assert not events_path.is_file()
