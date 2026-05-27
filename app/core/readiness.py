"""Startup readiness pass.

Runs ``run_health_checks()`` once at app boot and emits a single
``startup_readiness`` summary event with the rolled-up state. The
individual probe events still land in the events file as usual.

The summary event carries:
  - level:    info  if every probe is info
              warn  if any probe is warn (no errors)
              error if any probe is error
  - data:
      counts        {info, warn, error}
      checks        list of {kind, level, summary} per probe
      ready_for_ai  bool — ollama reachable + at least one model configured
                    is installed (or groq is configured as fallback)

The "ready_for_ai" flag is the single bit operators care about: can the
app actually serve a /query, /triage, /pivot, or /report call without
a backend failure.
"""

from __future__ import annotations

from app.core.events import (
    KIND_GROQ_CHECK,
    KIND_OLLAMA_CHECK,
    KIND_OLLAMA_MODELS_CHECK,
    KIND_STARTUP_READINESS,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARN,
    Event,
    record,
)
from app.core.health import run_health_checks


def _ready_for_ai(checks: list[Event]) -> bool:
    by_kind = {c.kind: c for c in checks}
    ollama = by_kind.get(KIND_OLLAMA_CHECK)
    models = by_kind.get(KIND_OLLAMA_MODELS_CHECK)
    groq = by_kind.get(KIND_GROQ_CHECK)
    ollama_ok = (
        ollama is not None
        and ollama.data.get("reachable") is True
        and models is not None
        and not models.data.get("missing", [])
    )
    groq_ok = groq is not None and groq.data.get("configured") is True
    return bool(ollama_ok or groq_ok)


async def run_startup_readiness() -> Event:
    """Run all health probes + emit the rolled-up startup_readiness event."""
    checks = await run_health_checks()
    # run_health_checks already appends a health_check summary at the tail.
    # Drop that one for the rolled-up event so we don't double-count.
    probes = [c for c in checks if c.kind != "health_check"]
    counts = {LEVEL_INFO: 0, LEVEL_WARN: 0, LEVEL_ERROR: 0}
    for e in probes:
        counts[e.level] = counts.get(e.level, 0) + 1
    if counts[LEVEL_ERROR]:
        level = LEVEL_ERROR
    elif counts[LEVEL_WARN]:
        level = LEVEL_WARN
    else:
        level = LEVEL_INFO
    ready_for_ai = _ready_for_ai(probes)
    summary = (
        f"startup readiness: {counts[LEVEL_INFO]} ok, "
        f"{counts[LEVEL_WARN]} warn, {counts[LEVEL_ERROR]} error; "
        f"ready_for_ai={ready_for_ai}"
    )
    return record(
        KIND_STARTUP_READINESS,
        "readiness",
        summary,
        level=level,
        counts=counts,
        ready_for_ai=ready_for_ai,
        checks=[
            {"kind": e.kind, "level": e.level, "summary": e.summary}
            for e in probes
        ],
    )
