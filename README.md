# gdorksAI

**AI-assisted Google dork reconnaissance for authorized penetration testing.**

A local web app that turns a curated Google-dork corpus into an AI-assisted recon workflow. Pentester picks a category or describes intent in plain English; a local LLM drafts the dork query; the operator opens the rendered Google URL in their own browser, pastes results back, and the AI ranks, dedupes, suggests pivots, and writes the engagement report — all behind a strict scope guard.

Built for authorized engagements only. There is no scraping, no headless browser, and no anti-detection logic.

## Status

**Phase 1 — in flight.** Phase 0 framework is on `main`. Phase 1 (registry + scope guard + web UI) is implemented across PRs #4, #5, #6 with CI green; awaiting stacked merge into main. See [docs/ROADMAP.md](docs/ROADMAP.md) for phase exit criteria.

## Operating principles

These are non-negotiable for the lifetime of v1. Changes require a security ticket.

1. **Operator-guided, not autonomous.** Every dork URL is clicked by the operator in their own browser. The server never fetches Google or any third party.
2. **Local-first AI.** Ollama is the default backend. Groq is an opt-in fallback (only used if `GROQ_API_KEY` is set). No outbound calls until the operator opts in.
3. **Scope guard everywhere.** Every render / query / triage / pivot / report call validates the target against `runtime/scope.json`. Refusals are logged; scope contents are never leaked back in error messages.
4. **No stealth.** No timing evasion, human mimicry, fingerprint randomization, or anti-detection behavior. The 200 ms HTMX debounce on the search input is a local UX choice, not pacing of an outbound request.
5. **No vendored corpus.** The dork data lives outside this repo and is loaded from `DORKS_DATA_PATH` at startup. Default is `data/dorks/` (gitignored).

## What it does (target state, end of Phase 3)

1. **Browse and search** the dork corpus by category or free text.
2. **Describe intent in natural language** → local LLM drafts a dork query (Phase 2, `query_gen` role).
3. **Click the rendered URL** to run the search in your own browser.
4. **Paste result snippets back** → LLM ranks, dedupes, flags high-value targets (Phase 2, `triage` role).
5. **Pivot from a finding** → LLM suggests related dorks (Phase 3, `pivot` role).
6. **Generate a Markdown report** of the session (Phase 3, `report` role).

## Quickstart

Requires Python 3.11+. Ollama running locally is optional in Phase 1 (no AI calls yet).

```bash
git clone https://github.com/cz4r777/gdorksAI.git
cd gdorksAI

python -m venv .venv
source .venv/bin/activate            # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

cp .env.example .env
# Edit .env: at minimum set DORKS_DATA_PATH and SCOPE_FILE

# Create a scope file with your authorized engagement targets
mkdir -p runtime
cat > runtime/scope.json <<'JSON'
{
  "engagement_id": "demo",
  "operator": "your-name",
  "authorized": ["example.com", "*.example.com"],
  "expires_at": "2026-12-31T23:59:59Z",
  "evidence": "path/to/authorization-letter.pdf"
}
JSON

uvicorn app.main:app --reload
# Visit http://127.0.0.1:8000
```

**Important:** without a `runtime/scope.json` containing the targets you intend to test, every render call returns 403. That is intentional — see [docs/SECURITY.md](docs/SECURITY.md).

## Framework

This is also a working example of a small-team opensource pipeline. Adopt or fork the pattern.

### Roles

| Role | Lives in | Owns |
|------|----------|------|
| Supervisor | a dedicated Claude session | ROADMAP, PIPELINE, ticket triage, design sign-off |
| Coder | a per-task Claude session | implementation, PRs |
| Security | reviewer (Claude or human) | per-PR security audit against a focus list |
| Operator | the human maintainer | merges, vendor decisions, ethics calls |

Handovers between roles use a single-block ASCII handover so they copy-paste cleanly between sessions.

### Pipeline

```
Ticket → Design → Branch → Implement → CI gate → Security review → Operator merge
```

- One ticket = one branch = one PR.
- Branch naming: `<type>/<issue-number>-<short-slug>` (e.g. `feature/2-scope-guard`).
- Ticket IDs in titles: `P<phase>-T<n>: …` so they sort.
- Squash merge only; PR title becomes the merge-commit subject.
- CI runs `ruff` + `mypy --strict` on `app/core` + `pytest` + import smoke. Red CI blocks review.
- Security review is gated on a focus list specific to the PR. See PR #5 and PR #6 comments for examples.

Full pipeline rules: [docs/PIPELINE.md](docs/PIPELINE.md). Workflow / labels / kanban: [docs/WORKFLOW.md](docs/WORKFLOW.md).

### Ticket types

`.github/ISSUE_TEMPLATE/` carries four templates:

- **feature** — new capability. Requires a design comment from the supervisor before code starts.
- **bug** — defect. Reproduce steps required. Skips design.
- **dork-category** — add/curate dork data. Lightweight review.
- **security** — for sensitive issues, prefer the private security advisory link in `.github/ISSUE_TEMPLATE/config.yml`.

### Labels

Canonical label set lives in [`.github/labels.yml`](.github/labels.yml). Apply with:

```bash
bash scripts/setup-labels.sh cz4r777/gdorksAI
```

Schema: `phase:0-4`, `area:registry|ai|web|scope|docs|ci`, `priority:p0|p1|p2`, `status:design|ready|in-progress|review|blocked`, `type:feature|bug|dork-category|security`.

## Project structure

```
app/
  main.py                     FastAPI app entry, /healthz
  web.py                      routes: GET / · GET /search · POST /render
  core/
    dorks.py                  registry: parse, search, render (scope-gated)
    scope.py                  scope guard: exact + wildcard host match, refuse-by-default
  templates/                  Jinja2 + HTMX partials
docs/                         ARCHITECTURE, ROADMAP, PIPELINE, WORKFLOW, SECURITY, AI_INTEGRATION
tests/                        pytest, mocks HTTP via httpx
.github/                      issue/PR templates, labels.yml, ci.yml
scripts/                      setup-labels.sh
data/dorks/                   (gitignored) where you put the dork corpus
runtime/                      (gitignored) scope.json, sessions, refusal log
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — system sketch, components, data flow, out-of-scope items
- [Roadmap](docs/ROADMAP.md) — phase plan and exit criteria
- [Pipeline](docs/PIPELINE.md) — how a change flows from ticket to merge
- [Workflow](docs/WORKFLOW.md) — roles, ticket types, labels, kanban
- [AI integration](docs/AI_INTEGRATION.md) — Ollama / Groq adapter, prompt versioning, scope-guard integration
- [Security](docs/SECURITY.md) — ethics, scope-guard contract, threat model, disclosure policy

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) (if present) and the [Pipeline](docs/PIPELINE.md). All work is tracked as GitHub Issues. Open a new issue using one of the templates; do not start code without an issue.

For security or scope-bypass reports that could enable misuse, **do not file a public issue**. Use the GitHub security advisory link in the issue picker.

## Attribution

The dork-category taxonomy and a large fraction of the example dorks in the public ecosystem trace back to [@Ishanoshada](https://github.com/Ishanoshada)'s [GDorks](https://github.com/Ishanoshada/GDorks) corpus. This repo does **not** vendor that corpus — the operator points `DORKS_DATA_PATH` at whatever source they choose — but the registry parsers in `app/core/dorks.py` are designed to read GDorks' published layout out of the box.

This is a fresh repository with no fork lineage. An earlier attempt to build on a direct fork (`cz4r777/GDorks-AI`) was abandoned for tooling reasons; that work is not carried forward here.

## License

MIT. See [LICENSE](LICENSE).
