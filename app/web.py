"""Web routes for the Phase 1 minimal UI.

Three endpoints:
- ``GET /``           home page (categories + search box)
- ``GET /search``     HTMX partial of matching dorks
- ``POST /render``    runs the scope-gated render, returns success or
                      refusal HTML partial

The page is intentionally inert: no auto-fetch, no scraping, no
background navigation. The operator clicks the rendered link in their
own browser.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.capabilities import build_state, compute_menu
from app.core.dorks import (
    DorkNotFoundError,
    DorkRegistry,
    InvalidTargetError,
    load_default_registry,
)
from app.core.events import events_file, read_recent
from app.core.health import run_health_checks
from app.core.scope import OutOfScopeError
from app.core.status import compute_snapshot

_TEMPLATES_DIR = "app/templates"
_RESULT_CAP = 200

router = APIRouter()
templates = Jinja2Templates(directory=_TEMPLATES_DIR)
templates.env.globals["compute_menu"] = compute_menu
templates.env.globals["build_state"] = build_state

_registry_singleton: DorkRegistry | None = None


def get_registry() -> DorkRegistry:
    """Lazy registry loader. Cached; reset for tests by clearing the global."""
    global _registry_singleton
    if _registry_singleton is None:
        _registry_singleton = load_default_registry()
    return _registry_singleton


def reset_registry() -> None:
    """Test helper. Clears the cached registry."""
    global _registry_singleton
    _registry_singleton = None


def google_search_url(query: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(query)}"


RegistryDep = Annotated[DorkRegistry, Depends(get_registry)]


@router.get("/diagnostics", response_class=HTMLResponse)
def diagnostics(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "diagnostics.html",
        {"events": read_recent(200), "events_file": str(events_file())},
    )


@router.post("/diagnostics/refresh", response_class=HTMLResponse)
async def diagnostics_refresh(request: Request) -> HTMLResponse:
    await run_health_checks()
    return templates.TemplateResponse(
        request,
        "_events_table.html",
        {"events": read_recent(200)},
    )


@router.get("/diagnostics.jsonl")
def diagnostics_jsonl() -> Response:
    path = events_file()
    if not path.is_file():
        return Response(content="", media_type="application/x-ndjson")
    return FileResponse(path, media_type="application/x-ndjson")


@router.get("/status", response_class=HTMLResponse)
def status_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "status.html",
        {"snapshot": compute_snapshot(request.app)},
    )


@router.post("/status/refresh", response_class=HTMLResponse)
async def status_refresh(request: Request) -> HTMLResponse:
    await run_health_checks()
    return templates.TemplateResponse(
        request,
        "_status_cards.html",
        {"snapshot": compute_snapshot(request.app)},
    )


@router.get("/", response_class=HTMLResponse)
def index(request: Request, registry: RegistryDep) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"categories": registry.list_categories()},
    )


@router.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    registry: RegistryDep,
    q: str = "",
    category: str = "",
) -> HTMLResponse:
    hits = registry.search(q=q or None, category=category or None)
    return templates.TemplateResponse(
        request,
        "_search_results.html",
        {"hits": hits[:_RESULT_CAP], "total": len(hits), "cap": _RESULT_CAP},
    )


@router.post("/render", response_class=HTMLResponse)
def render(
    request: Request,
    registry: RegistryDep,
    dork_id: Annotated[str, Form()],
    target: Annotated[str, Form()],
) -> HTMLResponse:
    try:
        query = registry.render(dork_id, target)
    except InvalidTargetError as e:
        return templates.TemplateResponse(
            request,
            "_render_refused.html",
            {"reason": "invalid target", "detail": str(e), "target": target},
            status_code=400,
        )
    except OutOfScopeError as e:
        return templates.TemplateResponse(
            request,
            "_render_refused.html",
            {"reason": "out of scope", "detail": str(e), "target": target},
            status_code=403,
        )
    except DorkNotFoundError as e:
        return templates.TemplateResponse(
            request,
            "_render_refused.html",
            {"reason": "unknown dork id", "detail": str(e), "target": target},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "_render_success.html",
        {
            "query": query,
            "url": google_search_url(query),
            "target": target.strip(),
        },
    )
