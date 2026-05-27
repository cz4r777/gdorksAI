# Changelog

All notable changes will be documented here. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0-alpha.1] — 2026-05-27

### Phase 1 — Dork registry + scope-gated render
- `app/core/dorks.py` — corpus parser, registry, `{target}` substitution
- `app/core/scope.py` — exact + wildcard host match, refuse-by-default
- `/`, `/search`, `/render` — home + search box + scope-gated render
- `/category/{name}` — single-category page, dorks grouped by source file
- `/dorks?page=N&per=M` — paginated all-dorks view (per ≤ 200)
- Category dropdown next to the search input

### Phase 2 — Local AI integration
- `app/core/ai.py` — async adapter, Ollama primary, Groq fallback only when configured, typed `AIAdapterError` with `AIErrorReason` enum, no silent degradation
- Pre-call scope assertion + post-call hostname scan on every model response
- `app/core/prompts/query_gen_v1.md`, `triage_v1.md` — single-line JSON output, `OUT_OF_SCOPE` sentinel
- `/query` — natural-language intent → AI-drafted dork(s)
- `/triage` — paste result snippets → AI ranks + server-side dedupes findings

### Phase 3 — Pivot + report
- `app/core/prompts/pivot_v1.md`, `report_v1.md`
- `/pivot` — paste a triaged finding → AI suggests same-target adjacent dorks
- `/report` — paste a session log → AI writes a Markdown writeup
- `app/core/sessions.py` — `/report` persists `runtime/sessions/<id>/report.md` + `meta.json`

### Operator-visible surfaces
- Persistent top-level nav with live capability detection (`app/capabilities.py`)
- Build-state badge (`bootstrap` / `phase-1` / `phase-2` / `phase-3`) derived from live route mounts
- `app/core/events.py` — append-only `runtime/events.jsonl` source of truth (metadata only)
- `app/core/health.py` — five non-destructive probes: ollama, groq, registry, scope, prompts
- `/diagnostics`, `/diagnostics/refresh`, `/diagnostics.jsonl`
- `app/core/status.py` — curated current-state snapshot derived from the event log
- `/status`, `/status/refresh`
- AI adapter emits `ai_call` and `ai_refused` events for every typed path (A1)
- `/report` emits `session_saved` event with metadata only — no prompt body, no full prompt hash

### Tooling / pipeline
- CI: `ruff check .`, `mypy --strict app/core`, `pytest -q`, import smoke
- Pipeline doc moved to "commit + push immediately" as the default checkpoint model
- Workflow doc: pushed branch is an acceptable review artifact alongside a PR

### Privacy / safety
- Refuse-by-default scope guard: missing or malformed `runtime/scope.json` → every render and AI call returns 403/422
- Events and session metadata files carry metadata only (no scope contents, no prompt body, no model output, no secrets)
- `runtime/` and `data/` are gitignored

### Known gaps
- No `/report` UI persistence beyond `runtime/sessions/<id>/` (no in-app session browser yet)
- No event-emission on `/render` refusals — only AI paths emit `ai_refused`
- Ollama / Groq model names are config-only; no model-availability probe yet
