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
- [ ] Scope guard refuses out-of-scope targets (P1-T2)
- [ ] Web UI: browse categories, search, get clickable URL with scope enforcement (P1-T3)

## Phase 2 — Local AI integration
- `app/core/ai.py` adapter with Ollama primary + Groq fallback.
- `/query` page: NL → dork suggestion (role: `query_gen`).
- `/triage` page: paste pasted result snippets, AI ranks + dedupes (role: `triage`).
**Exit criteria:** end-to-end NL→dork→triage works offline with Ollama; Groq fallback verified.

## Phase 3 — Pivot + report
- `/pivot` page: AI suggests related dorks based on a triaged finding (role: `pivot`).
- `/report` page: AI generates Markdown report for the session (role: `report`).
- Session persistence under `runtime/sessions/<id>/`.
**Exit criteria:** full recon session round-trip produces a saved report file.

## Phase 4 — Hardening + release
- Tests: pytest for registry, scope guard, AI adapter (mocked).
- Lint: ruff, mypy strict on `app/core/`.
- CI: GitHub Actions runs lint + tests on push/PR.
- Docs: usage walkthrough with screenshots, threat-model section in SECURITY.md.
- Tagged `v0.1.0` release.
**Exit criteria:** green CI, README quickstart works on a fresh clone.

## Phase 5 — Stretch (not committed)
Candidates, choose later:
- Browser extension for one-click "paste current Google results page back to triage."
- Multi-target / multi-session view.
- Plugin hook to be callable as a recon module by other tooling.
- Optional paid-API execution backend (SerpAPI / Brave) behind a feature flag.
