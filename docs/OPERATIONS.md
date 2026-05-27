# gdorksAI — Operations Manual

This is the single-page handoff doc for running gdorksAI as an alpha
operator. It does NOT replace [docs/SECURITY.md](SECURITY.md) (the
ethics contract) or [docs/ARCHITECTURE.md](ARCHITECTURE.md) (what the
system actually is). Read those first if you haven't.

## TL;DR

```bash
git clone https://github.com/cz4r777/gdorksAI.git
cd gdorksAI
python -m venv .venv
source .venv/bin/activate           # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env                 # edit DORKS_DATA_PATH + SCOPE_FILE

mkdir -p runtime
cat > runtime/scope.json <<'JSON'
{ "targets": ["example.com", "*.example.com"] }
JSON

uvicorn app.main:app --reload
# Visit http://127.0.0.1:8000
# First: http://127.0.0.1:8000/status   — confirms ready_for_ai
```

## Daily checks

1. Open `/status`. Confirm the overall badge is `all probes ok` (green).
2. If any card is `warn`, click **Run probes now** — sometimes Ollama
   was just slow on the first 2-second probe.
3. Open `/diagnostics`. Scroll the event log. You should see a
   `startup_readiness` event on every boot.
4. Open `/sessions`. Saved reports are listed newest-first.

## Quick reference — routes

| Route | What |
|---|---|
| `/` | Home — categories + search + dropdown |
| `/category/{name}` | One category, grouped by source file |
| `/dorks?page=N&per=M` | Flat paginated all-dorks (per ≤ 200) |
| `/diagnostics` | Last 200 events from `runtime/events.jsonl` |
| `/diagnostics/refresh` (POST) | Run all health probes |
| `/diagnostics.jsonl` | Raw JSONL export |
| `/status` | Current-state snapshot per component |
| `/status/refresh` (POST) | Re-run probes + swap snapshot |
| `/query` | NL intent → AI dork suggestion |
| `/triage` | Paste snippets → AI ranks + dedupes |
| `/pivot` | Triaged finding → same-target adjacent dorks |
| `/report` | Session log → Markdown writeup |
| `/report?from=<id>` | Compose new report from prior session |
| `/sessions` | List saved reports |
| `/sessions/{id}` | View one saved report |
| `/sessions/{id}/report.md` | Download raw Markdown |
| `/healthz` | `{"status":"ok"}` liveness |

## File layout you'll touch

```
runtime/
  scope.json         operator-edited; targets the engagement is authorized for
  events.jsonl       append-only diagnostic log
  sessions/
    <session-id>/
      report.md      AI-generated Markdown
      meta.json      {target, backend, prompt_filename, prompt_hash, ts}
```

`runtime/` is gitignored. Nothing under it ever ships to GitHub.

## Backup / rollback

Three things you might want to back up before a risky change:

1. **`runtime/scope.json`** — the engagement scope. Without this the
   app refuses every render/AI call. Back it up before edits.
2. **`runtime/sessions/`** — saved reports. They're the only durable
   record of past engagements.
3. **`runtime/events.jsonl`** — the diagnostic log. Optional, but
   useful for post-incident review.

Suggested approach for an engagement-day backup:

```bash
mkdir -p backups/$(date -u +%Y%m%d-%H%M%S)
cp -a runtime/scope.json runtime/events.jsonl runtime/sessions \
   backups/$(date -u +%Y%m%d-%H%M%S)/
```

Rollback is just `cp` the files back into `runtime/` and restart.

## When something breaks

| Symptom | First place to look |
|---|---|
| Every render returns 403 | `runtime/scope.json` exists? Targets listed? Restart app after editing |
| `/query` / `/triage` / `/pivot` / `/report` returns 503 | `/status` Ollama card; is Ollama running? |
| `/query` etc. returns 422 | Model leaked an off-scope hostname — scope guard caught it, expected |
| `/sessions` page is empty | Did `/report` ever complete? Check `/diagnostics` for `session_saved` events |
| `/status` shows "Ollama models" as warn | One of `OLLAMA_MODEL_QUERY/TRIAGE/PIVOT/REPORT` is set to a model not installed locally; run `ollama pull <name>` |
| First page after boot is slow | The startup readiness probe runs an HTTP call to Ollama. Set `GDORKSAI_SKIP_STARTUP_READINESS=1` to skip it |

## What changes from here

Per the alpha.2 release notes: **feature-branch work is paused**.
The queue from here is bugfixes, hardening, docs, and release support.
If a real operator gap appears, file an issue using the `feature`
template and supervisor sign-off will gate the next code change.

## Privacy contract (don't break)

- Events and session metadata are **metadata only** — no scope file
  contents, no prompt body, no model output, no secrets.
- Refuse-by-default scope guard: missing or malformed
  `runtime/scope.json` → every render/AI call returns 403/422.
- The server NEVER fetches Google or the target. Every dork URL is
  clicked by the operator in their own browser.
- No stealth / timing-evasion / fingerprint-randomization /
  anti-detection behavior of any kind.

See [docs/SECURITY.md](SECURITY.md) for the full ethics contract.
