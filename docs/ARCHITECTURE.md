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
