"""Live capability detection for the navigation menu.

Inspects the FastAPI router's actual mounted paths so the UI never lies
about what's available. Menu state is derived from live route mounts;
branch names, build flags, and version strings are deliberately not
consulted.

If a Phase 2/3 route isn't mounted, its menu item renders as
"coming soon" rather than being hidden. Operators always see the
intended target state and can tell at a glance what is and isn't built.
"""

from __future__ import annotations

from typing import TypedDict

from fastapi import FastAPI


class MenuItem(TypedDict):
    id: str
    label: str
    path: str
    hint: str
    phase: str
    available: bool


_STAGES: list[tuple[str, str, str, str, str]] = [
    (
        "home",
        "Home",
        "/",
        "Browse categories and search the dork corpus.",
        "1",
    ),
    (
        "diagnostics",
        "Diagnostics",
        "/diagnostics",
        "Event log: see what happened, when, and whether components are healthy.",
        "1",
    ),
    (
        "status",
        "Status",
        "/status",
        "Current-state snapshot derived from the event log.",
        "1",
    ),
    (
        "query",
        "Query",
        "/query",
        "Natural-language intent to AI-drafted dork.",
        "2",
    ),
    (
        "triage",
        "Triage",
        "/triage",
        "Paste result snippets; AI ranks and dedupes.",
        "2",
    ),
    (
        "pivot",
        "Pivot",
        "/pivot",
        "AI suggests related dorks for a triaged finding.",
        "3",
    ),
    (
        "report",
        "Report",
        "/report",
        "AI writes a Markdown report for the session.",
        "3",
    ),
]


def _mounted_paths(app: FastAPI) -> set[str]:
    return {getattr(r, "path", "") for r in app.routes}


def compute_menu(app: FastAPI) -> list[MenuItem]:
    """Build the navigation menu from the app's live route table."""
    paths = _mounted_paths(app)
    return [
        MenuItem(
            id=sid,
            label=label,
            path=path,
            hint=hint,
            phase=phase,
            available=path in paths,
        )
        for sid, label, path, hint, phase in _STAGES
    ]


def build_state(menu: list[MenuItem]) -> str:
    """Coarse build-state label derived from the menu, never from branch names.

    Returns one of: ``bootstrap``, ``phase-1``, ``phase-2``, ``phase-3``.

    - ``bootstrap``  - Home route absent; only the framework is loaded.
    - ``phase-1``    - Home available; no Phase 2 or 3 routes mounted.
    - ``phase-2``    - At least one Phase 2 route available.
    - ``phase-3``    - At least one Phase 3 route available.
    """
    home_ok = any(m["id"] == "home" and m["available"] for m in menu)
    p2_ok = any(m["phase"] == "2" and m["available"] for m in menu)
    p3_ok = any(m["phase"] == "3" and m["available"] for m in menu)
    if not home_ok:
        return "bootstrap"
    if p3_ok:
        return "phase-3"
    if p2_ok:
        return "phase-2"
    return "phase-1"
