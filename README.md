# gdorksAI

AI-assisted Google dork reconnaissance for authorized penetration testing.

A local web app where an authorized pentester can browse a curated dork registry, draft queries with the help of a local LLM, manually open the resulting Google URLs, paste result snippets back for triage, pivot from findings, and generate a Markdown engagement report — all under a strict scope guard.

## Status

**Phase 0 — Framework bootstrap.** Repo skeleton only; runtime features land in Phase 1+. See [docs/ROADMAP.md](docs/ROADMAP.md).

## What it does (target state)

1. Browse and search dork categories.
2. Describe intent in natural language → local AI (Ollama) drafts the dork query.
3. Open the dork URL in your own browser (no scraping, no automation).
4. Paste result snippets back → AI ranks, dedupes, and flags high-value targets.
5. Pivot from a finding → AI suggests related dorks.
6. Generate a Markdown engagement report from the session.

All AI roles (query gen, triage, pivot, report) run locally via Ollama. Groq is an opt-in fallback. No outbound calls by default.

## Quickstart (Phase 0 — skeleton only)

```bash
python -m venv .venv
source .venv/bin/activate     # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

cp .env.example .env
uvicorn app.main:app --reload
# Visit http://127.0.0.1:8000
```

The Phase 0 build serves a placeholder page and `/healthz` only. Real workflow lands in Phase 1.

## Ethics rails

This tool is for authorized engagements only. The scope guard refuses every query/triage/pivot/report call whose target is not in `runtime/scope.json`. See [docs/SECURITY.md](docs/SECURITY.md) for the full threat model and responsible-disclosure policy.

## Project structure

```
app/             FastAPI app
  core/          Dork registry, AI adapter, scope guard
  templates/     Jinja2 + HTMX fragments (Phase 1+)
docs/            ARCHITECTURE, ROADMAP, PIPELINE, WORKFLOW, SECURITY, AI_INTEGRATION
tests/           Pytest
.github/         Issue templates, PR template, CI, label config
scripts/         Setup helpers
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — system design
- [Roadmap](docs/ROADMAP.md) — phase plan and exit criteria
- [Pipeline](docs/PIPELINE.md) — how changes flow from ticket to merge
- [Workflow](docs/WORKFLOW.md) — roles, ticket types, kanban
- [AI integration](docs/AI_INTEGRATION.md) — Ollama / Groq, prompts, models
- [Security](docs/SECURITY.md) — ethics, scope, threat model

## License

MIT. See [LICENSE](LICENSE).
