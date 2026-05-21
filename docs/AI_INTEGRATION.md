# gdorksAI — AI Integration

## Backend priority

```
1. Ollama (localhost:11434)         ← default, local, no network
2. Groq API                          ← fallback if Ollama unreachable AND GROQ_API_KEY set
3. (future) LM Studio / llama.cpp    ← stretch
```

No call falls back silently. If both fail, the request returns a structured error and the UI shows it to the operator. Never substitute model output with a placeholder.

## Models (recommended starting set)

| Role | Ollama model | Groq fallback model | Notes |
|------|--------------|----------------------|-------|
| `query_gen` | `llama3.1:8b-instruct` | `llama-3.3-70b-versatile` | Short structured output |
| `triage` | `llama3.1:8b-instruct` | `llama-3.3-70b-versatile` | Json-mode preferred |
| `pivot` | `llama3.1:8b-instruct` | `llama-3.3-70b-versatile` | Few-shot from dork registry |
| `report` | `qwen2.5:14b-instruct` | `llama-3.3-70b-versatile` | Longer context for full session writeup |

Model IDs are config in `.env`, not hardcoded.

## Prompt versioning

System prompts live as files under `app/core/prompts/` named `<role>_v<n>.md`. Each call records the prompt filename + content hash in the session log. Prompts are reviewed in PR just like code.

## Determinism settings

| Role | Temperature | Top-p |
|------|-------------|-------|
| `query_gen` | 0.2 | 0.9 |
| `triage` | 0.1 | 0.9 |
| `pivot` | 0.3 | 0.9 |
| `report` | 0.5 | 0.95 |

## Scope-guard integration

Every prompt template includes a hardened instruction block:

```
You are assisting an authorized pentester. The target for this session is:
  AUTHORIZED_TARGET = {target_domain}

You MUST refuse to generate output that targets any other domain. If the
operator asks you to pivot to a domain outside AUTHORIZED_TARGET, respond
with the literal string OUT_OF_SCOPE and nothing else.
```

The wrapper code in `app/core/ai.py` additionally:
- Re-validates `target_domain` against `runtime/scope.json` before the call.
- Post-checks the model output for any domain not in scope; truncates/refuses if found.
- Logs every refusal with timestamp, role, target, and prompt hash.

## Cost & rate limits

Ollama: free, bound by local GPU/CPU. No rate limit logic needed.

Groq: per-key rate limit. Adapter retries with exponential backoff once, then surfaces the error. No silent degradation.

## Telemetry

Off by default. No outbound telemetry endpoints. Operator can enable a local SQLite log of (timestamp, role, latency, token counts) under `runtime/telemetry.db` via `.env`.
