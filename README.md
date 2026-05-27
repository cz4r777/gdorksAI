# gdorksAI

**AI-assisted Google dork reconnaissance for authorized penetration testing.**

A local FastAPI web app that turns a curated Google-dork corpus into an operator-guided recon workflow. The pentester picks a category or describes intent in plain English; a local LLM drafts the dork query; the operator opens the rendered Google URL in their own browser, pastes results back, and the AI ranks, dedupes, suggests pivots, and writes the engagement report — all behind a strict scope guard.

Built for authorized engagements only. No scraping, no headless browser, no anti-detection logic.

## Status

Phase 1 surface is implemented and Phase 2/3 routes render as "coming soon" via live capability detection. What's on `main` vs in flight is exposed in the UI itself — open `/diagnostics` and the nav bar's build-state badge shows the truth.

| Phase | Scope | State |
|---|---|---|
| 0 | Framework, CI, docs, ticket system | merged to `main` |
| 1 | Registry, scope guard, web UI, event log, health probes, nav menu | implemented across PRs #14, #15, #18 |
| 2 | Local AI adapter (Ollama → Groq); `/query`, `/triage` | designed; coding next |
| 3 | `/pivot`, `/report`, session persistence | planned |
| 4 | Hardening, security headers, vendored assets, `v0.1.0` | planned |

See [docs/ROADMAP.md](docs/ROADMAP.md) for phase exit criteria.

## Operating principles

Non-negotiable for v1. Changes require a security ticket.

1. **Operator-guided, not autonomous.** The server never fetches Google or any third party. Every dork URL is clicked by the operator in their own browser.
2. **Local-first AI.** Ollama is the default backend. Groq is opt-in (only used when `GROQ_API_KEY` is set). No outbound calls until the operator opts in.
3. **Scope guard everywhere.** Every render / query / triage / pivot / report call validates the target against `runtime/scope.json`. Refuse-by-default if the file is missing or malformed. Refusals are logged at WARNING on `gdorksai.scope`; scope contents are never leaked in error messages.
4. **Append-only diagnostic log.** Every probe, refusal, and lifecycle event is recorded as a JSON line in `runtime/events.jsonl`. Metadata only — no scope contents, no prompt bodies, no target hostnames being investigated.
5. **No stealth.** No timing evasion, human mimicry, fingerprint randomization, or detection-avoidance behavior. The 200 ms HTMX debounce on the search input is local UX, not request pacing.

## Quickstart

Python 3.11+. Ollama is optional in Phase 1 (no AI calls yet); the diagnostics page will simply show it as unreachable.

```bash
git clone https://github.com/cz4r777/gdorksAI.git
cd gdorksAI

python -m venv .venv
source .venv/bin/activate            # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

cp .env.example .env
# Edit .env: at minimum set DORKS_DATA_PATH and SCOPE_FILE

# Bootstrap a scope file with your authorized targets — without this,
# every render call returns 403. That is intentional.
mkdir -p runtime
cat > runtime/scope.json <<'JSON'
{
  "targets": [
    "example.com",
    "*.example.com"
  ]
}
JSON

uvicorn app.main:app --reload
# http://127.0.0.1:8000                  home / search
# http://127.0.0.1:8000/diagnostics      event log + health probes
```

## Surface

| Route | Method | What |
|---|---|---|
| `/` | GET | Home — categories + search |
| `/search` | GET | HTMX partial; full-text + category filter, capped at 200 hits |
| `/render` | POST | Scope-gated; returns the Google URL for the operator to click. `400 / 403 / 404` for invalid / out-of-scope / unknown dork |
| `/diagnostics` | GET | Last 200 events from `runtime/events.jsonl` |
| `/diagnostics/refresh` | POST | Run all health probes, re-render the event table |
| `/diagnostics.jsonl` | GET | Raw JSONL export |
| `/healthz` | GET | `{"status":"ok"}` liveness |

Phase 2/3 routes (`/query`, `/triage`, `/pivot`, `/report`) are wired into the nav menu as "coming soon" until their handlers mount.

## Health probes

`POST /diagnostics/refresh` runs five non-destructive probes and writes one event per probe:

- **ollama** — `GET $OLLAMA_HOST/api/tags`, 2-second timeout
- **groq** — checks `GROQ_API_KEY` presence (no outbound call)
- **registry** — loads `DORKS_DATA_PATH`, counts records and categories
- **scope** — loads `runtime/scope.json`, counts exact + wildcard entries
- **prompts** — globs `app/core/prompts/*_v*.md`, counts files

## Project layout

```
app/
  main.py                 FastAPI entry, lifespan, /healthz
  web.py                  routes: / · /search · /render · /diagnostics
  capabilities.py         live route detection -> nav menu + build state
  core/
    dorks.py              registry: parse corpus, search, scope-gated render
    scope.py              scope guard: exact + wildcard host match, refuse-by-default
    events.py             append-only JSONL event log (metadata only)
    health.py             5 probes; each emits a typed event
  templates/              Jinja2 + HTMX (htmx 1.9.12 + Tailwind via CDN)
docs/                     ARCHITECTURE, ROADMAP, PIPELINE, WORKFLOW, SECURITY, AI_INTEGRATION
tests/                    pytest; mocks HTTP via httpx.MockTransport
.github/                  issue/PR templates, labels.yml, ci.yml
scripts/                  setup-labels.sh
data/dorks/               (gitignored) where you put the dork corpus
runtime/                  (gitignored) scope.json, events.jsonl
```

## Framework (how this project is run)

- **Roles.** Supervisor (docs, ticket triage, design sign-off), Coder (one ticket → one branch → one PR), Security (per-PR audit against a focus list), Operator (merge decisions). Each lives in a separate session; handovers cross sessions as single-block ASCII blocks.
- **Pipeline.** `Ticket → Design → Branch → Implement → CI gate → Security review → Operator merge`. CI runs `ruff` + `mypy --strict app/core` + `pytest` + import smoke. Red CI blocks review.
- **Tickets.** Four templates in `.github/ISSUE_TEMPLATE/`: `feature`, `bug`, `dork-category`, `security`. Title format `P<phase>-T<n>: …` so they sort.
- **Labels.** Apply with `bash scripts/setup-labels.sh cz4r777/gdorksAI`.

Full rules: [docs/PIPELINE.md](docs/PIPELINE.md) and [docs/WORKFLOW.md](docs/WORKFLOW.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — system sketch, components, data flow
- [Roadmap](docs/ROADMAP.md) — phase plan and exit criteria
- [Pipeline](docs/PIPELINE.md) — change flow
- [Workflow](docs/WORKFLOW.md) — roles, ticket types, kanban
- [AI integration](docs/AI_INTEGRATION.md) — Ollama / Groq adapter, prompt versioning, scope-guard integration
- [Security](docs/SECURITY.md) — ethics, scope-guard contract, threat model, disclosure

## Attribution

The dork-category taxonomy in the public ecosystem traces back to [@Ishanoshada](https://github.com/Ishanoshada)'s [GDorks](https://github.com/Ishanoshada/GDorks) corpus. This repo does **not** vendor that corpus — the operator points `DORKS_DATA_PATH` at whatever source they choose — but the registry parsers in `app/core/dorks.py` are designed to read the published layout out of the box.

This is a fresh repository with no fork lineage.

## License

MIT. See [LICENSE](LICENSE).
