"""Operator status snapshot — curated view of the diagnostic event log.

The /status page condenses recent events (from P1-T7's ``events.jsonl``)
into a single snapshot per component (Ollama, Groq, registry, scope,
prompts) plus the live capability menu. Source of truth remains the
events file — the snapshot is a presentation layer over it.

If no recent events exist for a component, the field is ``None`` and the
UI shows "not yet observed" with a button to run probes inline.

Privacy carry-over from P1-T7: snapshot fields are metadata only, no
scope contents, no secrets, no prompt body. The status surface inherits
the events file's safety guarantees by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI

from app.capabilities import MenuItem, compute_menu
from app.core.events import (
    KIND_GROQ_CHECK,
    KIND_OLLAMA_CHECK,
    KIND_PROMPTS_CHECK,
    KIND_REGISTRY_LOADED,
    KIND_SCOPE_LOADED,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARN,
    Event,
    read_recent,
)

OVERALL_OK = "ok"
OVERALL_DEGRADED = "degraded"
OVERALL_MISSING = "missing"


@dataclass(frozen=True)
class StatusSnapshot:
    overall: str
    ollama: Event | None
    groq: Event | None
    registry: Event | None
    scope: Event | None
    prompts: Event | None
    menu: list[MenuItem]


def _latest_by_kind(events: list[Event]) -> dict[str, Event]:
    """Return the most-recent event seen for each kind in the input list."""
    out: dict[str, Event] = {}
    for e in events:
        out[e.kind] = e
    return out


def _overall(probes: list[Event | None]) -> str:
    non_null = [p for p in probes if p is not None]
    if not non_null:
        return OVERALL_MISSING
    levels = {p.level for p in non_null}
    if LEVEL_ERROR in levels or LEVEL_WARN in levels:
        return OVERALL_DEGRADED
    if LEVEL_INFO in levels:
        return OVERALL_OK
    return OVERALL_MISSING


def compute_snapshot(app: FastAPI) -> StatusSnapshot:
    """Build the current snapshot from the latest events plus live route table."""
    events = read_recent(500)
    by_kind = _latest_by_kind(events)
    ollama = by_kind.get(KIND_OLLAMA_CHECK)
    groq = by_kind.get(KIND_GROQ_CHECK)
    registry = by_kind.get(KIND_REGISTRY_LOADED)
    scope = by_kind.get(KIND_SCOPE_LOADED)
    prompts = by_kind.get(KIND_PROMPTS_CHECK)
    return StatusSnapshot(
        overall=_overall([ollama, groq, registry, scope, prompts]),
        ollama=ollama,
        groq=groq,
        registry=registry,
        scope=scope,
        prompts=prompts,
        menu=compute_menu(app),
    )
