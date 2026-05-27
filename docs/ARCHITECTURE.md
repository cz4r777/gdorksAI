# gdorksAI — Architecture

## One-liner
Web tool that turns a curated dork corpus into an AI-assisted reconnaissance workflow for authorized pentesting.

## System sketch
```
┌──────────────────────────────────────────────────────────┐
│ Browser (HTMX + Tailwind)                                │
│  - Query builder UI                                      │
│  - Paste-results pane                                    │
│  - Triage / pivot / report panels                        │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP (HTMX partials)
┌────────────────────────▼─────────────────────────────────┐
│ FastAPI app                                              │
│  routes/    - query, triage, pivot, report               │
│  core/      - dork registry, AI adapter, scope guard     │
│  templates/ - Jinja2 + HTMX fragments                    │
└────────┬────────────────────────────────┬────────────────┘
         │                                │
┌────────▼────────────┐         ┌─────────▼──────────────┐
│ Dork registry       │         │ AI adapter             │
│ (reads DORKS_DATA_  │         │  primary: Ollama       │
│   PATH)             │         │  fallback: Groq        │
│  - categories       │         │  optional: LMStudio    │
│  - search/filter    │         │                        │
└─────────────────────┘         └────────────────────────┘
```

## Components

### Dork registry (`app/core/dorks.py`)
- Reads dork corpus from the directory pointed at by `DORKS_DATA_PATH` (see `.env.example`).
- Expected layout: per-category subdirectories of text files, plus a flat JSON catalog.
- Concrete file list is finalized in P1-T1 (issue tracker) — the registry must not assume the directory is inside this repo.
- Normalizes to a single in-memory index: `{id, category, query, source_file}`.
- Provides: search by keyword/category, list categories, render with `{target}` substitution.

### AI adapter (`app/core/ai.py`)
- Single interface: `generate(prompt, role) -> str`.
- Routes to Ollama (localhost:11434) by default. Falls back to Groq when Ollama unreachable or model missing.
- Roles: `query_gen`, `triage`, `pivot`, `report`. Each role has its own system prompt template under `app/core/prompts/`.

### Scope guard (`app/core/scope.py`)
- Every render/query/triage/pivot/report call must reference a target domain inside the operator's authorized scope, loaded from `runtime/scope.json` (override with `SCOPE_FILE`).
- Refuses to render or execute if the target is not in scope. Refusals are logged with target + caller label + scope file path.
- Missing or malformed scope file => refuse-all (secure default).
- Scope file format:
  ```json
  { "targets": ["example.com", "*.example.com", "research.example.org"] }
  ```
  - Exact host entries match that host only.
  - `*.example.com` matches subdomains (`a.example.com`, `a.b.example.com`) but NOT the apex — add an explicit `example.com` for the apex.
  - Hostnames are normalized (lower-cased, trailing dot stripped).
- This is the ethics rail: the tool will not assist on unauthorized targets.

### Web layer
- FastAPI + Jinja2 + HTMX partials. No SPA build.
- Tailwind via CDN in v1; bundle later if needed.
- One page per workflow stage (query → triage → pivot → report) with HTMX swaps.

### Diagnostic event log (`app/core/events.py` + `app/core/health.py`)
- Append-only JSON-lines file at `runtime/events.jsonl` (override with `EVENTS_FILE`). One event per line, oldest-first.
- This file is the **source of truth** for "what happened in this session" — UI surfaces and external diagnostic tools both read from it. App state itself (registry, scope) lives in live objects; events are the audit/diagnostic surface.
- Event shape: `{ts, kind, level, component, summary, data}`. Kinds are frozen for v1 (startup, registry_loaded, scope_loaded, ollama_check, groq_check, prompts_check, routes_mounted, health_check, scope_refused, ai_call, ai_refused, error). Levels: info / warn / error.
- Privacy: events carry **metadata only** — no scope contents, no secrets, no prompt body, no model output.
- `health.run_health_checks()` runs five cheap probes and emits one event per probe: ollama reachability (2-second HTTP probe), Groq key presence (no outbound call), registry load, scope file state, prompts directory.
- `/diagnostics` renders the last 200 events; `/diagnostics.jsonl` streams the raw file; `/diagnostics/refresh` re-runs the probes.

### Navigation & capability detection (`app/capabilities.py`)
- A persistent top-level menu lists every intended workflow stage (Home, Diagnostics, Status, Query, Triage, Pivot, Report).
- "Available" vs "Coming soon" is derived from the live FastAPI route table, **not** from branch names, build flags, or hand-maintained version strings. If the route isn't mounted, the menu item is disabled.
- `build_state(menu)` returns a coarse label (`bootstrap` / `phase-1` / `phase-2` / `phase-3`) for the header badge — also derived from live route mounts.
- Future phase routes (Query/Triage/Pivot/Report) appear as "coming soon" until their respective tickets ship, so the operator always sees the target state and the current state side-by-side.

## Data flow (single recon session)
1. Operator declares a target + uploads/links the engagement scope.
2. Operator picks a category or types intent → AI generates dork(s).
3. Operator opens the rendered Google URL in their browser (manual click — no scraper).
4. Operator pastes result snippets back into the triage pane.
5. AI ranks, dedupes, flags high-value URLs.
6. AI suggests pivots (related dorks for the same finding class).
7. Operator iterates. When done, AI writes the Markdown report.

## What is explicitly out of scope (v1)
- No Google scraping. No headless browser. No proxy rotation.
- No multi-user / team features. Single operator, localhost.
- No background workers. Sync request/response only.
- No exploit execution. Recon-only.

## Local-first by default
- Default profile = Ollama + no outbound calls. Operator must opt in to Groq fallback by setting `GROQ_API_KEY`.
- All session data (scope, queries, pastes, reports) lives on disk under `runtime/`, never sent anywhere.

## Delivery model
- Operationally, the project now assumes incremental pushed checkpoints.
- The canonical recovery mechanism for implementation work is git history on the remote branch, not long-lived hidden local state.
- Review can happen on a PR or directly on the pushed branch, but code should normally be visible off-machine after each meaningful update.

## Dork data sourcing
- The dork corpus is **not** vendored into this repo. The registry reads from `DORKS_DATA_PATH`, which the operator points at a local directory.
- Acceptable sources: a curated local subset under `data/dorks/`, or an external sibling directory the operator owns.
- Initial data layout to be specified in P1-T1.
