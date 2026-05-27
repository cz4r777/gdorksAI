"""Web routes for the Phase 1 minimal UI + Phase 2/3 AI workflows.

Endpoints:
- ``GET /``           home page (categories + search box)
- ``GET /search``     HTMX partial of matching dorks
- ``POST /render``    runs the scope-gated render, returns success or
                      refusal HTML partial
- ``GET /query``      query page form
- ``POST /query``     calls AI adapter (query_gen), parses suggestions
- ``GET /triage``     triage page form (paste snippets)
- ``POST /triage``    calls AI adapter (triage), parses + dedupes
                      findings server-side, returns ranked partial
- ``GET /pivot``      pivot page form (paste a triaged finding)
- ``POST /pivot``     calls AI adapter (pivot), parses suggestions for
                      same-target adjacent dorks, returns partial
- ``GET /report``     report page form (paste session log)
- ``POST /report``    calls AI adapter (report), returns Markdown
                      session writeup

The page is intentionally inert: no auto-fetch, no scraping, no
background navigation. The operator clicks links in their own browser.
"""

from __future__ import annotations

import json
from typing import Annotated, Any
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app.capabilities import build_state, compute_menu
from app.core.ai import (
    AIAdapter,
    AIAdapterError,
    AIErrorReason,
    AIRequest,
    load_default_adapter,
)
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


_adapter_singleton: AIAdapter | None = None


def get_adapter() -> AIAdapter:
    """Lazy AI adapter loader. Override in tests via dependency_overrides."""
    global _adapter_singleton
    if _adapter_singleton is None:
        _adapter_singleton = load_default_adapter()
    return _adapter_singleton


def reset_adapter() -> None:
    """Test helper. Clears the cached default adapter."""
    global _adapter_singleton
    _adapter_singleton = None


AdapterDep = Annotated[AIAdapter, Depends(get_adapter)]


_AI_REASON_TO_HTTP: dict[AIErrorReason, int] = {
    AIErrorReason.OUT_OF_SCOPE_OUTPUT: 422,
    AIErrorReason.NO_BACKEND_AVAILABLE: 503,
    AIErrorReason.OLLAMA_UNREACHABLE: 503,
    AIErrorReason.OLLAMA_MODEL_MISSING: 503,
    AIErrorReason.GROQ_NOT_CONFIGURED: 503,
    AIErrorReason.GROQ_RATE_LIMITED: 429,
    AIErrorReason.PROMPT_NOT_FOUND: 500,
}


def _http_for_ai_reason(reason: AIErrorReason) -> int:
    return _AI_REASON_TO_HTTP.get(reason, 502)


def _parse_query_suggestions(text: str, target: str) -> list[dict[str, Any]]:
    """Parse query_gen output into suggestion objects.

    Tries JSON object(s); falls back to a single raw suggestion if nothing
    parses. Each suggestion has a pre-rendered Google URL so the template
    can render a clickable link directly.
    """
    out: list[dict[str, Any]] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        dork = str(obj.get("dork", "")).strip()
        if not dork:
            continue
        rendered = dork.replace("{target}", target)
        out.append(
            {
                "dork": dork,
                "rendered": rendered,
                "url": google_search_url(rendered),
                "category": str(obj.get("category", "uncategorized")),
                "rationale": str(obj.get("rationale", "")),
                "structured": True,
            }
        )
    if not out:
        raw = text.strip()
        rendered = raw.replace("{target}", target)
        out.append(
            {
                "dork": raw,
                "rendered": rendered,
                "url": google_search_url(rendered),
                "category": "raw",
                "rationale": "model output could not be parsed as structured JSON",
                "structured": False,
            }
        )
    return out


@router.get("/", response_class=HTMLResponse)
def index(request: Request, registry: RegistryDep) -> HTMLResponse:
    categories = registry.list_categories()
    counts = {c: len(registry.search(category=c)) for c in categories}
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "categories": categories,
            "counts": counts,
            "total": len(registry),
        },
    )


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


@router.get("/category/{name}", response_class=HTMLResponse)
def category_page(
    request: Request, name: str, registry: RegistryDep
) -> HTMLResponse:
    hits = registry.search(category=name)
    groups: dict[str, list] = {}
    for r in hits:
        groups.setdefault(r.source_file, []).append(r)
    status = 200 if hits else 404
    return templates.TemplateResponse(
        request,
        "category.html",
        {
            "category": name,
            "groups": groups,
            "total": len(hits),
            "categories": registry.list_categories(),
        },
        status_code=status,
    )


_DORKS_PER_PAGE_DEFAULT = 50
_DORKS_PER_PAGE_MAX = 200


@router.get("/dorks", response_class=HTMLResponse)
def dorks_list(
    request: Request,
    registry: RegistryDep,
    page: int = 1,
    per: int = _DORKS_PER_PAGE_DEFAULT,
) -> HTMLResponse:
    page = max(1, page)
    per = max(1, min(per, _DORKS_PER_PAGE_MAX))
    all_hits = registry.search()
    total = len(all_hits)
    start = (page - 1) * per
    end = start + per
    hits = all_hits[start:end]
    pages = max(1, (total + per - 1) // per)
    return templates.TemplateResponse(
        request,
        "dorks.html",
        {
            "hits": hits,
            "page": page,
            "per": per,
            "total": total,
            "pages": pages,
        },
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


@router.get("/query", response_class=HTMLResponse)
def query_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "query.html", {})


@router.post("/query", response_class=HTMLResponse)
async def query_submit(
    request: Request,
    adapter: AdapterDep,
    target: Annotated[str, Form()] = "",
    intent: Annotated[str, Form()] = "",
) -> HTMLResponse:
    target_clean = target.strip()
    intent_clean = intent.strip()
    if not target_clean or not intent_clean:
        return templates.TemplateResponse(
            request,
            "_query_error.html",
            {
                "reason": "missing input",
                "detail": "Both target and intent are required.",
                "target": target_clean,
            },
            status_code=400,
        )
    try:
        resp = await adapter.generate(
            AIRequest(
                role="query_gen",
                target=target_clean,
                user_input=intent_clean,
            )
        )
    except OutOfScopeError as e:
        return templates.TemplateResponse(
            request,
            "_query_error.html",
            {
                "reason": "out of scope",
                "detail": str(e),
                "target": target_clean,
            },
            status_code=403,
        )
    except AIAdapterError as e:
        return templates.TemplateResponse(
            request,
            "_query_error.html",
            {
                "reason": e.reason.value,
                "detail": str(e),
                "target": target_clean,
            },
            status_code=_http_for_ai_reason(e.reason),
        )
    suggestions = _parse_query_suggestions(resp.text, target_clean)
    return templates.TemplateResponse(
        request,
        "_query_results.html",
        {
            "suggestions": suggestions,
            "target": target_clean,
            "backend": resp.backend,
        },
    )


_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _parse_triage_findings(
    text: str,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Parse triage model output.

    Returns (findings, duplicates_dropped, refused).

    - If output is the literal "OUT_OF_SCOPE" sentinel, returns
      ([], 0, True). The web layer renders the refusal block.
    - Otherwise expects a JSON array of finding objects. Server-side
      dedupes by `dedup_key` (lower-cased, stripped), keeping the first
      occurrence. Counts the number of duplicates collapsed for the UI.
    - Findings without a `url` field are dropped silently.
    """
    stripped = text.strip()
    if stripped == "OUT_OF_SCOPE":
        return [], 0, True
    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError:
        return [], 0, False
    if not isinstance(raw, list):
        return [], 0, False
    seen: dict[str, dict[str, Any]] = {}
    dropped = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        if not url:
            continue
        priority = str(item.get("priority", "low")).strip().lower()
        if priority not in _PRIORITY_ORDER:
            priority = "low"
        dedup_key = str(item.get("dedup_key", url)).strip().lower()
        if not dedup_key:
            dedup_key = url.lower()
        if dedup_key in seen:
            dropped += 1
            continue
        seen[dedup_key] = {
            "url": url,
            "title": str(item.get("title", "")).strip(),
            "priority": priority,
            "why": str(item.get("why", "")).strip(),
            "dedup_key": dedup_key,
        }
    findings = sorted(
        seen.values(),
        key=lambda f: (_PRIORITY_ORDER[f["priority"]], f["url"]),
    )
    return findings, dropped, False


@router.get("/triage", response_class=HTMLResponse)
def triage_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "triage.html", {})


@router.post("/triage", response_class=HTMLResponse)
async def triage_submit(
    request: Request,
    adapter: AdapterDep,
    target: Annotated[str, Form()] = "",
    snippets: Annotated[str, Form()] = "",
) -> HTMLResponse:
    target_clean = target.strip()
    snippets_clean = snippets.strip()
    if not target_clean or not snippets_clean:
        return templates.TemplateResponse(
            request,
            "_query_error.html",
            {
                "reason": "missing input",
                "detail": "Both target and pasted snippets are required.",
                "target": target_clean,
            },
            status_code=400,
        )
    try:
        resp = await adapter.generate(
            AIRequest(
                role="triage",
                target=target_clean,
                user_input=snippets_clean,
            )
        )
    except OutOfScopeError as e:
        return templates.TemplateResponse(
            request,
            "_query_error.html",
            {
                "reason": "out of scope",
                "detail": str(e),
                "target": target_clean,
            },
            status_code=403,
        )
    except AIAdapterError as e:
        return templates.TemplateResponse(
            request,
            "_query_error.html",
            {
                "reason": e.reason.value,
                "detail": str(e),
                "target": target_clean,
            },
            status_code=_http_for_ai_reason(e.reason),
        )
    findings, duplicates, refused = _parse_triage_findings(resp.text)
    if refused:
        return templates.TemplateResponse(
            request,
            "_query_error.html",
            {
                "reason": "out of scope",
                "detail": (
                    "All pasted snippets pointed outside the authorized "
                    "scope; the AI refused the whole set."
                ),
                "target": target_clean,
            },
            status_code=422,
        )
    return templates.TemplateResponse(
        request,
        "_triage_results.html",
        {
            "findings": findings,
            "duplicates": duplicates,
            "target": target_clean,
            "backend": resp.backend,
            "parsed": len(findings) > 0,
        },
    )


@router.get("/pivot", response_class=HTMLResponse)
def pivot_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "pivot.html", {})


@router.post("/pivot", response_class=HTMLResponse)
async def pivot_submit(
    request: Request,
    adapter: AdapterDep,
    target: Annotated[str, Form()] = "",
    finding: Annotated[str, Form()] = "",
) -> HTMLResponse:
    target_clean = target.strip()
    finding_clean = finding.strip()
    if not target_clean or not finding_clean:
        return templates.TemplateResponse(
            request,
            "_query_error.html",
            {
                "reason": "missing input",
                "detail": "Both target and finding are required.",
                "target": target_clean,
            },
            status_code=400,
        )
    try:
        resp = await adapter.generate(
            AIRequest(
                role="pivot",
                target=target_clean,
                user_input=finding_clean,
            )
        )
    except OutOfScopeError as e:
        return templates.TemplateResponse(
            request,
            "_query_error.html",
            {
                "reason": "out of scope",
                "detail": str(e),
                "target": target_clean,
            },
            status_code=403,
        )
    except AIAdapterError as e:
        return templates.TemplateResponse(
            request,
            "_query_error.html",
            {
                "reason": e.reason.value,
                "detail": str(e),
                "target": target_clean,
            },
            status_code=_http_for_ai_reason(e.reason),
        )
    if resp.text.strip() == "OUT_OF_SCOPE":
        return templates.TemplateResponse(
            request,
            "_query_error.html",
            {
                "reason": "out of scope",
                "detail": (
                    "The finding referenced an off-scope domain; the AI "
                    "refused to generate pivot suggestions."
                ),
                "target": target_clean,
            },
            status_code=422,
        )
    suggestions = _parse_query_suggestions(resp.text, target_clean)
    return templates.TemplateResponse(
        request,
        "_query_results.html",
        {
            "suggestions": suggestions,
            "target": target_clean,
            "backend": resp.backend,
        },
    )
