"""Health probes — emit one diagnostic event per probe.

Probes are deliberately cheap and non-destructive:

- ``ollama``      GET ``OLLAMA_HOST/api/tags`` with a 2-second timeout
- ``groq``        check ``GROQ_API_KEY`` presence; no outbound call (we
                  never burn the operator's free tier just to look)
- ``registry``    instantiate from ``DORKS_DATA_PATH``; count records
- ``scope``       instantiate the scope guard; count loaded targets
- ``prompts``     glob ``app/core/prompts/*_v*.md``; count files

Probes call :func:`app.core.events.record` so the diagnostic page (and
any external tool watching the JSONL file) reflects current health.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from app.core.dorks import load_default_registry
from app.core.events import (
    KIND_GROQ_CHECK,
    KIND_HEALTH_CHECK,
    KIND_OLLAMA_CHECK,
    KIND_OLLAMA_MODELS_CHECK,
    KIND_PROMPTS_CHECK,
    KIND_REGISTRY_LOADED,
    KIND_SCOPE_LOADED,
    LEVEL_ERROR,
    LEVEL_INFO,
    LEVEL_WARN,
    Event,
    record,
)
from app.core.scope import ScopeGuard

_PROBE_TIMEOUT = 2.0


_OLLAMA_MODEL_ROLE_ENVS = {
    "query_gen": "OLLAMA_MODEL_QUERY",
    "triage": "OLLAMA_MODEL_TRIAGE",
    "pivot": "OLLAMA_MODEL_PIVOT",
    "report": "OLLAMA_MODEL_REPORT",
}


def _configured_ollama_models() -> dict[str, str]:
    out: dict[str, str] = {}
    for role, env in _OLLAMA_MODEL_ROLE_ENVS.items():
        v = os.environ.get(env, "").strip()
        if v:
            out[role] = v
    return out


async def probe_ollama() -> Event:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as c:
            r = await c.get(f"{host}/api/tags")
        if r.status_code == 200:
            return record(
                KIND_OLLAMA_CHECK,
                "ollama",
                f"ollama reachable at {host}",
                level=LEVEL_INFO,
                host=host,
                reachable=True,
                detail=f"HTTP {r.status_code}",
            )
        return record(
            KIND_OLLAMA_CHECK,
            "ollama",
            f"ollama responded HTTP {r.status_code} at {host}",
            level=LEVEL_WARN,
            host=host,
            reachable=False,
            detail=f"HTTP {r.status_code}",
        )
    except httpx.HTTPError as e:
        return record(
            KIND_OLLAMA_CHECK,
            "ollama",
            f"ollama unreachable at {host}",
            level=LEVEL_WARN,
            host=host,
            reachable=False,
            detail=type(e).__name__,
        )


async def probe_ollama_models() -> Event:
    """Compare configured per-role Ollama models against the installed set.

    Emits one event with a per-role breakdown: which configured models are
    installed, which are missing. The model-name list itself is metadata, not
    secret. If Ollama is unreachable the event is WARN with
    ``reachable=false``.
    """
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    configured = _configured_ollama_models()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as c:
            r = await c.get(f"{host}/api/tags")
    except httpx.HTTPError as e:
        return record(
            KIND_OLLAMA_MODELS_CHECK,
            "ollama",
            f"ollama unreachable; cannot verify configured models at {host}",
            level=LEVEL_WARN,
            host=host,
            reachable=False,
            detail=type(e).__name__,
            configured=configured,
        )
    if r.status_code != 200:
        return record(
            KIND_OLLAMA_MODELS_CHECK,
            "ollama",
            f"ollama /api/tags returned HTTP {r.status_code}",
            level=LEVEL_WARN,
            host=host,
            reachable=False,
            detail=f"HTTP {r.status_code}",
            configured=configured,
        )
    try:
        data = r.json()
    except ValueError as e:
        return record(
            KIND_OLLAMA_MODELS_CHECK,
            "ollama",
            "ollama /api/tags returned non-JSON",
            level=LEVEL_WARN,
            host=host,
            reachable=True,
            detail=type(e).__name__,
            configured=configured,
        )
    raw = data.get("models", []) if isinstance(data, dict) else []
    installed: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model")
                if isinstance(name, str) and name:
                    installed.append(name)
    installed_set = set(installed)
    by_role: dict[str, dict[str, object]] = {}
    missing: list[str] = []
    for role, model in configured.items():
        ok = model in installed_set
        by_role[role] = {"model": model, "installed": ok}
        if not ok:
            missing.append(f"{role}:{model}")
    summary = (
        f"all {len(configured)} configured ollama models installed"
        if configured and not missing
        else f"{len(missing)} configured ollama model(s) missing: {', '.join(missing)}"
        if missing
        else "no per-role ollama models configured"
    )
    level = LEVEL_WARN if missing else LEVEL_INFO
    return record(
        KIND_OLLAMA_MODELS_CHECK,
        "ollama",
        summary,
        level=level,
        host=host,
        reachable=True,
        configured=configured,
        installed=sorted(installed),
        missing=missing,
        by_role=by_role,
    )


def probe_groq() -> Event:
    configured = bool(os.environ.get("GROQ_API_KEY"))
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    if configured:
        return record(
            KIND_GROQ_CHECK,
            "groq",
            "groq fallback configured (key present)",
            level=LEVEL_INFO,
            configured=True,
            model=model,
        )
    return record(
        KIND_GROQ_CHECK,
        "groq",
        "groq fallback not configured (no GROQ_API_KEY)",
        level=LEVEL_INFO,
        configured=False,
        model=model,
    )


def probe_registry() -> Event:
    path = os.environ.get("DORKS_DATA_PATH", "data/dorks")
    try:
        reg = load_default_registry()
        count = len(reg)
        cats = len(reg.list_categories())
    except Exception as e:
        return record(
            KIND_REGISTRY_LOADED,
            "registry",
            f"registry load failed for {path}",
            level=LEVEL_ERROR,
            path=path,
            error=type(e).__name__,
        )
    level = LEVEL_INFO if count > 0 else LEVEL_WARN
    summary = (
        f"registry loaded {count} dorks across {cats} categories from {path}"
        if count > 0
        else f"registry path {path} produced 0 dorks (empty / missing corpus)"
    )
    return record(
        KIND_REGISTRY_LOADED,
        "registry",
        summary,
        level=level,
        path=path,
        dork_count=count,
        category_count=cats,
    )


def probe_scope() -> Event:
    path = os.environ.get("SCOPE_FILE", "runtime/scope.json")
    guard = ScopeGuard()
    # Trigger load; uses internal lazy-load on first is_in_scope call.
    guard.is_in_scope("__healthprobe__")
    # Access the now-populated counts via internal attrs.
    exact = len(guard._exact)  # noqa: SLF001 — probe is the closest reader
    wildcards = len(guard._wildcards)  # noqa: SLF001
    file_exists = Path(path).is_file()
    total = exact + wildcards
    if not file_exists:
        return record(
            KIND_SCOPE_LOADED,
            "scope",
            f"scope file missing at {path} — refuse-all in effect",
            level=LEVEL_WARN,
            path=path,
            file_exists=False,
            target_count=0,
        )
    level = LEVEL_INFO if total > 0 else LEVEL_WARN
    return record(
        KIND_SCOPE_LOADED,
        "scope",
        f"scope file loaded with {total} entries ({exact} exact, {wildcards} wildcard)",
        level=level,
        path=path,
        file_exists=True,
        target_count=total,
        exact_count=exact,
        wildcard_count=wildcards,
    )


def probe_prompts() -> Event:
    pdir = Path(os.environ.get("PROMPTS_DIR", "app/core/prompts"))
    if not pdir.is_dir():
        return record(
            KIND_PROMPTS_CHECK,
            "prompts",
            f"prompts directory not found at {pdir}",
            level=LEVEL_WARN,
            path=str(pdir),
            count=0,
        )
    files = sorted(p.name for p in pdir.glob("*_v*.md"))
    level = LEVEL_INFO if files else LEVEL_WARN
    summary = (
        f"prompts directory has {len(files)} files"
        if files
        else f"prompts directory {pdir} has no <role>_v<n>.md files"
    )
    return record(
        KIND_PROMPTS_CHECK,
        "prompts",
        summary,
        level=level,
        path=str(pdir),
        count=len(files),
        files=files,
    )


async def run_health_checks() -> list[Event]:
    """Run all probes; emit one event per probe; return them in order.

    Emits a final summary event with the count by level. Probes are
    independent — one failing does not skip the rest.
    """
    events: list[Event] = []
    events.append(await probe_ollama())
    events.append(await probe_ollama_models())
    events.append(probe_groq())
    events.append(probe_registry())
    events.append(probe_scope())
    events.append(probe_prompts())
    counts = {LEVEL_INFO: 0, LEVEL_WARN: 0, LEVEL_ERROR: 0}
    for e in events:
        counts[e.level] = counts.get(e.level, 0) + 1
    summary_level = (
        LEVEL_ERROR if counts[LEVEL_ERROR]
        else LEVEL_WARN if counts[LEVEL_WARN]
        else LEVEL_INFO
    )
    events.append(
        record(
            KIND_HEALTH_CHECK,
            "health",
            (
                f"health check complete: {counts[LEVEL_INFO]} ok, "
                f"{counts[LEVEL_WARN]} warn, {counts[LEVEL_ERROR]} error"
            ),
            level=summary_level,
            counts=counts,
        )
    )
    return events
