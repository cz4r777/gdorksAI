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
- Async interface: `await adapter.generate(AIRequest) -> AIResponse`.
- Routes to Ollama (localhost:11434) by default. Falls back to Groq only when Ollama is unreachable OR the role's model is missing AND `GROQ_API_KEY` is set. If neither backend is usable, raises `AIAdapterError(NO_BACKEND_AVAILABLE)` — no silent degradation.
- Roles: `query_gen`, `triage`, `pivot`, `report`. Each role has its own prompt template under `app/core/prompts/<role>_v<n>.md` (highest version wins). Prompt files use `---SYSTEM---` / `---USER---` markers.
- Per-call rails (in order):
  1. `scope_guard.assert_in_scope(target)` before any backend call. Out-of-scope target raises `OutOfScopeError` and no backend traffic is emitted.
  2. Prompt file is rendered with the request vars; filename + sha256 of the rendered content are recorded on every call.
  3. Backend call (async httpx). Typed errors via `AIAdapterError(reason: AIErrorReason)` — e.g. `OLLAMA_UNREACHABLE`, `OLLAMA_MODEL_MISSING`, `GROQ_RATE_LIMITED`.
  4. Post-call hostname scan: any hostname found in the model's output that is not in scope refuses the entire response with `OUT_OF_SCOPE_OUTPUT`. The model never gets to leak an alternate target through us.
- Tests mock the HTTP layer via `httpx.MockTransport`; CI does not require a live Ollama.

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

### Navigation & capability detection (`app/capabilities.py`)
- A persistent top-level menu lists every intended workflow stage (Home, Status, Query, Triage, Pivot, Report).
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

## Dork data sourcing
- The dork corpus is **not** vendored into this repo. The registry reads from `DORKS_DATA_PATH`, which the operator points at a local directory.
- Acceptable sources: a curated local subset under `data/dorks/`, or an external sibling directory the operator owns.
- Initial data layout to be specified in P1-T1.
