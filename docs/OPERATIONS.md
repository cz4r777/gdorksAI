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

## AI workflow troubleshooting

When `/query`, `/triage`, `/pivot`, or `/report` returns an error, the
response template surfaces a typed `reason` string and a recent slice
of `runtime/events.jsonl`. The reason is the truth — read it before
guessing.

### Reading the runtime config card

Before debugging an AI workflow, open `/status` and skim the
**Effective runtime config** card. It shows the live values of
`OLLAMA_HOST`, the four `OLLAMA_MODEL_*` slots, the Groq key
(presence-only), and `GROQ_MODEL`. Most AI-workflow failures resolve
to "the value here is wrong / unset / pointing somewhere the network
can't reach."

### Reason codes

| `reason` | What happened | First action |
|---|---|---|
| `ollama_unreachable` | TCP/HTTP to `OLLAMA_HOST` failed (host down, wrong port, firewall) | Confirm `OLLAMA_HOST` on `/status`. `curl $OLLAMA_HOST/api/tags`. Start `ollama serve` if missing. |
| `ollama_model_missing` | Ollama is up but the model named in `OLLAMA_MODEL_<role>` isn't pulled locally | `ollama pull <model>`. Then `ollama list` to verify. |
| `ollama_http_error` | Ollama returned a non-2xx (often OOM, model load failure, or a malformed request hitting a stale model) | Check `ollama logs` / the Ollama server console. Try a smaller model in `OLLAMA_MODEL_<role>` if OOM. |
| `groq_not_configured` | Ollama failed AND `GROQ_API_KEY` is unset, so no fallback was tried | Either fix Ollama or export `GROQ_API_KEY=...` and restart. `/status` confirms the key is `configured`. |
| `groq_rate_limited` | Groq returned 429 | Wait, or switch back to local Ollama by fixing the Ollama problem so fallback isn't needed. |
| `groq_http_error` | Groq returned a non-2xx other than 429 (auth, payload, server) | Double-check `GROQ_API_KEY` and `GROQ_MODEL`. Inspect the `ai_call_failed` event payload in `/diagnostics`. |
| `no_backend_available` | Both Ollama and Groq are unusable | Fix at least one. The app refuses to fabricate output when no backend is up. |
| `out_of_scope_output` | The model returned a hostname not in `runtime/scope.json` | Expected behavior — scope guard caught a hallucination. Either retry, or add the target via the "✓ I am authorized" button if the result is legitimate. |
| `prompt_not_found` | The role's prompt template is missing from `PROMPTS_DIR` | Confirm `PROMPTS_DIR` on `/status` points at `app/core/prompts/` (or wherever your customized prompts live), and that `query_gen.md` / `triage.md` / `pivot.md` / `report.md` exist there. |
| `malformed_response` | Model output didn't match the expected JSON shape | Often a too-small / unfit model. Switch `OLLAMA_MODEL_<role>` to a JSON-capable model (e.g. `qwen2.5:7b-instruct`, `llama3.1:8b-instruct`). |

### Workflow-specific notes

- **/query** — the only workflow that accepts a free-text *intent*. If
  the model is consistently producing dorks that miss your intent, the
  fix is usually a stronger model in `OLLAMA_MODEL_QUERY`, not prompt
  edits.
- **/triage** — needs realistic snippets. Pasting in 2-line snippets
  makes the model guess; pasting in the actual search-result snippet
  with surrounding text gives much better dedup + ranking.
- **/pivot** — refuses if the input finding isn't on a target in
  `runtime/scope.json`. This is intentional and matches the render-time
  scope guard.
- **/report** — composes from a session id. If `/sessions` is empty,
  there's nothing to report on. Run at least one /query → /triage →
  /pivot cycle first, then `/report?from=<session-id>`.

### Where the evidence lives

| Want to see... | Look here |
|---|---|
| Which backend the call actually used | `ai_call_succeeded` events in `/diagnostics` — payload includes `backend: ollama` or `backend: groq` |
| Why a call failed | `ai_call_failed` events — payload includes `reason` and `role` |
| What model name was tried | `ai_call_attempt` events — payload includes `model` and `backend` |
| Whether the scope guard intercepted a model output | `ai_output_refused` events — payload includes `reason: out_of_scope` |
| The current live env values | `/status` → Effective runtime config card |

All events are metadata-only by contract: prompts, model output, and
target hostnames never appear in payloads. Don't try to "fix" that by
adding fields — see [docs/SECURITY.md](SECURITY.md).

### Common multi-step failures

- **"Everything started working then stopped"** — the most common
  cause is that Ollama crashed silently. `ollama ps` should list the
  models you expect to be loaded. Restart `ollama serve`.
- **"It worked locally but the deployed instance fails"** — compare
  the `/status` runtime-config card on both. The usual culprit is a
  different `DORKS_DATA_PATH` or `PROMPTS_DIR` resolving to an empty
  directory on the server.
- **"Groq fallback never kicks in"** — Groq is only used when Ollama
  fails with `ollama_unreachable` or `ollama_model_missing`. An
  `ollama_http_error` is treated as a *real* error from a working
  backend, not as a trigger to fall back. If you want Groq used while
  Ollama is misbehaving in that mode, stop Ollama entirely.

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

See [docs/SECURITY.md](SECURITY.md) for the full ethics contract.
