# gdorksAI — Roadmap

Phases are gated, not time-boxed. Each phase ends with a working demo and a tagged release.

## Phase 0 — Framework (this PR)
Bootstrap repo: docs, ticket templates, CI, project skeleton. No runtime features yet.
**Exit criteria:** repo published, framework docs reviewed, Phase 1 tickets filed.

## Phase 1 — Dork registry + query builder
- Parse a configured dork corpus (path from `DORKS_DATA_PATH`) into a single in-memory index.
- `/` page: list categories, search, render dork URL with target substitution.
- Scope guard: target must be in `runtime/scope.json`; refuse otherwise.
- No AI yet.

**Exit criteria:**
- [x] Registry parses configured dork corpus into normalized records (P1-T1)
- [x] Scope guard refuses out-of-scope targets, integrated into render (P1-T2)
- [x] Web UI: browse categories, search, get clickable URL with scope enforcement (P1-T3)

## Phase 2 — Local AI integration
- `app/core/ai.py` adapter with Ollama primary + Groq fallback.
- `/query` page: NL → dork suggestion (role: `query_gen`).
- `/triage` page: paste result snippets, AI ranks + dedupes (role: `triage`).

**Exit criteria:**
- [x] Async AI adapter with Ollama primary + Groq fallback, scope-gated, no silent degradation (P2-T1)
- [x] /query page wired to query_gen role (P2-T2)
- [x] /triage page wired to triage role (P2-T3)

## Phase 3 — Pivot + report
- `/pivot` page: AI suggests related dorks based on a triaged finding (role: `pivot`).
- `/report` page: AI generates Markdown report for the session (role: `report`).
- Session persistence under `runtime/sessions/<id>/`.

**Exit criteria:**
- [x] /pivot page wired to pivot role (P3-T1)
- [x] /report page wired to report role (A2)
- [x] Session persistence to `runtime/sessions/<id>/report.md` + `meta.json` (A3)

## Phase 4 — Hardening + alpha release
- Tests: pytest for registry, scope guard, AI adapter (mocked), events, health, status, sessions.
- Lint: ruff, mypy strict on `app/core/`.
- CI: GitHub Actions runs lint + tests on push/PR.
- Diagnostic event log wired into AI calls (A1).
- Docs truth-pass (A4); alpha cut (A5).
**Exit criteria:** green CI, README quickstart works on a fresh clone, `v0.1.0-alpha.1` tagged.

## Phase 5 — Stretch (not committed)
Candidates, choose later:
- Browser extension for one-click "paste current Google results page back to triage."
- Multi-target / multi-session view.
- Plugin hook to be callable as a recon module by other tooling.
- Optional paid-API execution backend (SerpAPI / Brave) behind a feature flag.
