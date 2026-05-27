"""Diagnostic event log — append-only JSON-lines source of truth.

The events file (default ``runtime/events.jsonl``, override with the
``EVENTS_FILE`` env var) is the canonical record of what happened in this
session. UI surfaces and external diagnostic tools both read from it; no
state is derived from anywhere else when answering "did X happen?".

Privacy / safety
----------------
Events carry **metadata only**:

* component names, summaries, counts, durations, hostnames-of-services
  (e.g. ``http://localhost:11434``)
* numeric results of probes (reachable Y/N, target count, prompt count)

Events DO NOT carry:

* scope file contents (target list)
* secrets, API keys, env values
* prompt body, model output, or user input
* dork queries, target hostnames being investigated

Format
------
One JSON object per line::

    {"ts": "2026-05-22T10:00:00+00:00",
     "kind": "ollama_check",
     "level": "warn",
     "component": "ollama",
     "summary": "ollama unreachable at http://localhost:11434",
     "data": {"host": "http://localhost:11434", "reachable": false}}

Failure mode
------------
If the events file is not writable, ``record`` logs the failure to the
standard Python logger and returns the event anyway. We never raise out
of a diagnostic emit — diagnostics must not break the request path they
were observing.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DEFAULT_FILE = "runtime/events.jsonl"
_ENV_KEY = "EVENTS_FILE"
_LOG = logging.getLogger("gdorksai.events")
_LOCK = threading.Lock()

# Frozen enums for v1 — extending requires a ticket and an ARCHITECTURE update.
KIND_STARTUP = "startup"
KIND_REGISTRY_LOADED = "registry_loaded"
KIND_SCOPE_LOADED = "scope_loaded"
KIND_OLLAMA_CHECK = "ollama_check"
KIND_GROQ_CHECK = "groq_check"
KIND_PROMPTS_CHECK = "prompts_check"
KIND_ROUTES_MOUNTED = "routes_mounted"
KIND_HEALTH_CHECK = "health_check"
KIND_SCOPE_REFUSED = "scope_refused"
KIND_AI_CALL = "ai_call"
KIND_AI_REFUSED = "ai_refused"
KIND_DORK_RENDER = "dork_render"
KIND_DORK_REFUSED = "dork_refused"
KIND_SESSION_SAVED = "session_saved"
KIND_ERROR = "error"

LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"


@dataclass(frozen=True)
class Event:
    ts: str
    kind: str
    level: str
    component: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


def events_file() -> Path:
    return Path(os.environ.get(_ENV_KEY, _DEFAULT_FILE))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def record(
    kind: str,
    component: str,
    summary: str,
    *,
    level: str = LEVEL_INFO,
    **data: Any,
) -> Event:
    """Append a single event to the events file. Never raises.

    The event is returned for caller convenience. If the file is not
    writable the event is still constructed and a warning is logged.
    """
    event = Event(
        ts=_now(),
        kind=kind,
        level=level,
        component=component,
        summary=summary,
        data=dict(data),
    )
    path = events_file()
    line = json.dumps(asdict(event), separators=(",", ":"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        _LOG.warning("could not write event to %s: %s", path, e)
    return event


def read_recent(n: int = 200) -> list[Event]:
    """Tail the last ``n`` events. Returns oldest-first.

    Missing file -> empty list. Bad lines are skipped silently — the log
    is best-effort, not authoritative for state.
    """
    path = events_file()
    if not path.is_file():
        return []
    with _LOCK:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            _LOG.warning("could not read events file %s: %s", path, e)
            return []
    tail = lines[-n:] if n > 0 else []
    out: list[Event] = []
    for line in tail:
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        out.append(
            Event(
                ts=str(raw.get("ts", "")),
                kind=str(raw.get("kind", "")),
                level=str(raw.get("level", LEVEL_INFO)),
                component=str(raw.get("component", "")),
                summary=str(raw.get("summary", "")),
                data=raw["data"] if isinstance(raw.get("data"), dict) else {},
            )
        )
    return out


def clear_for_test() -> None:
    """Test helper: delete the events file if it exists."""
    path = events_file()
    if path.is_file():
        path.unlink()
