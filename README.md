# gdorksAI

**AI-assisted Google dork reconnaissance for authorized penetration testing.**

A local FastAPI web app that turns a curated Google-dork corpus into an operator-guided recon workflow. The pentester picks a category or describes intent in plain English; a local LLM drafts the dork query; the operator opens the rendered Google URL in their own browser, pastes results back, and the AI ranks, dedupes, suggests pivots, and writes the engagement report — all behind a strict scope guard.

Built for authorized engagements only. No scraping, no headless browser, no anti-detection logic.

## Status

**`v0.1.0-alpha.2`** — current alpha. See [CHANGELOG.md](CHANGELOG.md).

Phase 1, 2, and 3 surfaces are all on `main`. The nav bar's build-state badge reads `phase-3` and every workflow stage (Home, Diagnostics, Status, Query, Triage, Pivot, Report, Sessions) is mounted. What's actually running is exposed in the UI itself — open `/status` or `/diagnostics` for a live snapshot derived from the diagnostic event log.

Since alpha.1: ops-readiness self-check, /status surface for effective runtime config, one-click "authorize this target" button, saved-session browser, and a graceful non-HTMX fallback so the AI forms keep working when the htmx CDN is blocked.

## Working style

This project now prefers immediate pushed checkpoints over long local-only holds:

1. make a code change
2. commit it
3. push it immediately
4. use the pushed branch as the backup / rollback point
5. review or merge later when convenient

If a change is risky, make smaller commits and push each checkpoint. The goal is to keep progress visible, reversible, and not blocked on stacked merge choreography.

Before any batch of related edits, take a fresh backup checkpoint first:

1. confirm the current branch is in a known-good state
2. commit any finished work
3. push that checkpoint
4. start the next batch from there

That backup-first rule is the default for coder work. Do not wait for a special merge window before pushing progress.

## Operating principles

Non-negotiable for v1. Changes require a security ticket.

1. **Operator-guided, not autonomous.** The server never fetches Google or any third party. Every dork URL is clicked by the operator in their own browser.
2. **Local-first AI.** Ollama is the default backend. Groq is opt-in (only used when `GROQ_API_KEY` is set). No outbound calls until the operator opts in.
3. **Scope guard everywhere.** Every render / query / triage / pivot / report call validates the target against `runtime/scope.json`. Refuse-by-default if the file is missing or malformed. Refusals are logged at WARNING on `gdorksai.scope`; scope contents are never leaked in error messages.
4. **Append-only diagnostic log.** Every probe, refusal, and lifecycle event is recorded as a JSON line in `runtime/events.jsonl`. Metadata only — no scope contents, no prompt bodies, no target hostnames being investigated.
5. **No stealth.** No timing evasion, human mimicry, fingerprint randomization, or detection-avoidance behavior. The 200 ms HTMX debounce on the search input is local UX, not request pacing.

## Setup

### Dependencies (required)

- **[Python 3.11+](https://www.python.org/downloads/)** — the FastAPI app targets CPython 3.11 or newer.
- **[Uvicorn](https://www.uvicorn.org/)** — ASGI server that runs the app. Installed automatically by `pip install -e ".[dev]"`; no separate install required. Reference: [Uvicorn deployment docs](https://www.uvicorn.org/deployment/).
- A dork corpus on disk — point `DORKS_DATA_PATH` at the directory. The upstream [@Ishanoshada/GDorks](https://github.com/Ishanoshada/GDorks) repo is the canonical source and is known to load out of the box.

### Dependencies (for AI workflows)

`/query`, `/triage`, `/pivot`, and `/report` need an LLM backend. Without one, those routes return 503 and the diagnostics page shows the backend as unreachable.

- **[Ollama](https://ollama.com/download)** — local LLM runtime, the default and recommended backend (fully offline once models are pulled). After install:

  ```bash
  ollama serve                                # starts the daemon on :11434
  ollama pull llama3.1:8b-instruct            # query_gen / triage / pivot
  ollama pull qwen2.5:14b-instruct            # report
  ```

  Model docs: [ollama.com/library](https://ollama.com/library). API reference: [Ollama REST API](https://github.com/ollama/ollama/blob/main/docs/api.md).

- **[Groq](https://console.groq.com/)** — opt-in cloud fallback used only when Ollama is unreachable. Set `GROQ_API_KEY` in `.env` to enable it; leave it blank to stay fully local with no outbound calls. API docs: [console.groq.com/docs](https://console.groq.com/docs).

### Development environment (recommended)

This repo's pipeline is run by multiple parallel **[Claude Code](https://claude.ai/code)** sessions — one each for supervisor, coder, security, and operator — coordinating via single-block ASCII handovers. Not required to *run* the app; required to follow the project's development workflow as documented in [docs/WORKFLOW.md](docs/WORKFLOW.md). Claude Code install: [claude.ai/code](https://claude.ai/code). API & SDK: [docs.claude.com](https://docs.claude.com).

### Steps

```bash
git clone https://github.com/cz4r777/gdorksAI.git
cd gdorksAI

# 1. Python venv + install
python -m venv .venv
source .venv/bin/activate                    # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# 2. Config — copy template, then edit DORKS_DATA_PATH + SCOPE_FILE
cp .env.example .env

# 3. Scope file — without this, every /render returns 403 (intentional)
mkdir -p runtime
cat > runtime/scope.json <<'JSON'
{
  "targets": [
    "example.com",
    "*.example.com"
  ]
}
JSON

# 4. (Optional) start Ollama in a separate terminal
ollama serve

# 5. Run the app
uvicorn app.main:app --reload
# http://127.0.0.1:8000                       home / search / authorize
# http://127.0.0.1:8000/diagnostics           event log + health probes
# http://127.0.0.1:8000/status                runtime config snapshot
# http://127.0.0.1:8000/sessions              saved /report writeups
```

For daily-use checks, backups, rollback, and common-breakage recipes see the [Operations manual](docs/OPERATIONS.md).

## Surface

| Route | Method | What |
|---|---|---|
| `/` | GET | Home — categories + search box (with category dropdown) |
| `/search` | GET | HTMX partial; full-text + category filter, capped at 200 hits |
| `/category/{name}` | GET | One-category page, dorks grouped by source file |
| `/dorks?page=N&per=M` | GET | Paginated flat all-dorks view (per ≤ 200) |
| `/render` | POST | Scope-gated; returns the Google URL for the operator to click. `400 / 403 / 404` for invalid / out-of-scope / unknown dork |
| `/scope/authorize` | POST | One-click "add this target to `runtime/scope.json`" button, used from the refusal page |
| `/diagnostics` | GET | Last 200 events from `runtime/events.jsonl` |
| `/diagnostics/refresh` | POST | Run all health probes, re-render the event table |
| `/diagnostics.jsonl` | GET | Raw JSONL export |
| `/status` | GET | Curated snapshot per-component (latest event per kind) + effective runtime config |
| `/status/refresh` | POST | Re-run probes, swap the snapshot cards |
| `/query` | GET/POST | NL intent → AI-drafted dork(s); JSON parsed into clickable URLs |
| `/triage` | GET/POST | Paste result snippets → AI ranks + server-side dedupes findings |
| `/pivot` | GET/POST | Paste a triaged finding → AI suggests same-target adjacent dorks |
| `/report` | GET/POST | Paste a session log → AI writes Markdown report; saved under `runtime/sessions/<id>/` |
| `/sessions` | GET | Index of saved /report writeups, newest first |
| `/sessions/{id}` | GET | Detail page for one saved session |
| `/sessions/{id}/report.md` | GET | Raw Markdown download for one saved session |
| `/healthz` | GET | `{"status":"ok"}` liveness |

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
  main.py                 FastAPI entry, lifespan emits startup events, /healthz
  web.py                  routes: home/search/render/category/dorks/diagnostics/
                          status/query/triage/pivot/report
  capabilities.py         live route detection -> nav menu + phase build state
  core/
    dorks.py              registry: parse corpus, search, scope-gated render
    scope.py              scope guard: exact + wildcard host match, refuse-by-default
    ai.py                 async adapter — Ollama primary, Groq fallback, scope rails,
                          ai_call/ai_refused event emission
    prompts/              <role>_v<n>.md: query_gen, triage, pivot, report
    events.py             append-only JSONL event log (metadata only)
    health.py             5 probes; each emits a typed event
    status.py             curated snapshot over the latest event per kind
    sessions.py           /report writes runtime/sessions/<id>/report.md + meta.json
  templates/              Jinja2 + HTMX (htmx 1.9.12 + Tailwind via CDN)
docs/                     ARCHITECTURE, ROADMAP, PIPELINE, WORKFLOW, SECURITY, AI_INTEGRATION
tests/                    pytest; mocks HTTP via httpx.MockTransport
.github/                  issue/PR templates, labels.yml, ci.yml
scripts/                  setup-labels.sh
data/dorks/               (gitignored) where you put the dork corpus
runtime/                  (gitignored) scope.json, events.jsonl, sessions/<id>/
```

## Framework (how this project is run)

- **Roles.** Supervisor (docs, ticket triage, design sign-off), Coder (ticket work and pushed checkpoints), Security (review against a focus list), Operator (accepts the next working baseline). Each lives in a separate session; handovers cross sessions as single-block ASCII blocks.
- **Pipeline.** `Ticket → Design → Branch → Backup checkpoint → Implement → Commit → Push → CI/use → Review → Land when convenient`. CI runs `ruff` + `mypy --strict app/core` + `pytest` + import smoke. Red CI blocks landing, not visibility.
- **Tickets.** Four templates in `.github/ISSUE_TEMPLATE/`: `feature`, `bug`, `dork-category`, `security`. Title format `P<phase>-T<n>: …` so they sort.
- **Labels.** Apply with `bash scripts/setup-labels.sh cz4r777/gdorksAI`.

Full rules: [docs/PIPELINE.md](docs/PIPELINE.md) and [docs/WORKFLOW.md](docs/WORKFLOW.md).

## Documentation

- [Operations manual](docs/OPERATIONS.md) — daily checks, backups, rollback, common breakage
- [Architecture](docs/ARCHITECTURE.md) — system sketch, components, data flow
- [Roadmap](docs/ROADMAP.md) — phase plan and exit criteria
- [Pipeline](docs/PIPELINE.md) — how changes flow from ticket to pushed code and landing
- [Workflow](docs/WORKFLOW.md) — roles, ticket types, kanban
- [AI integration](docs/AI_INTEGRATION.md) — Ollama / Groq adapter, prompt versioning, scope-guard integration
- [Security](docs/SECURITY.md) — ethics, scope-guard contract, threat model, disclosure
- [Changelog](CHANGELOG.md) — what landed in each release

## Attribution

The dork-category taxonomy in the public ecosystem traces back to [@Ishanoshada](https://github.com/Ishanoshada)'s [GDorks](https://github.com/Ishanoshada/GDorks) corpus. This repo does **not** vendor that corpus — the operator points `DORKS_DATA_PATH` at whatever source they choose — but the registry parsers in `app/core/dorks.py` are designed to read the published layout out of the box.

This is a fresh repository with no fork lineage.

## License & credit

MIT — free to use, modify, and redistribute, **provided the copyright notice is retained**. See [LICENSE](LICENSE).

Copyright © 2026 Conrad Brookes &lt;conrad.brookes@gmail.com&gt;. If you use, fork, or build on this project, please keep the attribution in source and in any user-facing About / Credits surface.
