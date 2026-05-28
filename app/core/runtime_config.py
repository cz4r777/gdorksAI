"""Effective runtime-config snapshot.

Reads the env vars and on-disk paths the app is actually using right now,
so operators can spot config drift from the /status page without grepping
the events log. The output is metadata only — secrets are reported as
"configured" / "not configured" booleans, never the value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeConfigEntry:
    name: str
    label: str
    value: str
    is_secret: bool = False


@dataclass(frozen=True)
class RuntimeConfigSnapshot:
    paths: list[RuntimeConfigEntry]
    ai_backend: list[RuntimeConfigEntry]


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _flag(name: str) -> str:
    """Reports presence-only for sensitive env vars (e.g. API keys)."""
    return "configured" if os.environ.get(name) else "not configured"


def compute_runtime_config() -> RuntimeConfigSnapshot:
    paths = [
        RuntimeConfigEntry(
            "DORKS_DATA_PATH",
            "dork corpus",
            _env("DORKS_DATA_PATH", "data/dorks"),
        ),
        RuntimeConfigEntry(
            "SCOPE_FILE",
            "scope file",
            _env("SCOPE_FILE", "runtime/scope.json"),
        ),
        RuntimeConfigEntry(
            "EVENTS_FILE",
            "events log",
            _env("EVENTS_FILE", "runtime/events.jsonl"),
        ),
        RuntimeConfigEntry(
            "SESSIONS_DIR",
            "sessions dir",
            _env("SESSIONS_DIR", "runtime/sessions"),
        ),
        RuntimeConfigEntry(
            "PROMPTS_DIR",
            "prompts dir",
            _env("PROMPTS_DIR", "app/core/prompts"),
        ),
    ]
    ai_backend = [
        RuntimeConfigEntry(
            "OLLAMA_HOST",
            "Ollama host",
            _env("OLLAMA_HOST", "http://localhost:11434"),
        ),
        RuntimeConfigEntry(
            "OLLAMA_MODEL_QUERY",
            "Ollama / query_gen",
            _env("OLLAMA_MODEL_QUERY", "(not set)"),
        ),
        RuntimeConfigEntry(
            "OLLAMA_MODEL_TRIAGE",
            "Ollama / triage",
            _env("OLLAMA_MODEL_TRIAGE", "(not set)"),
        ),
        RuntimeConfigEntry(
            "OLLAMA_MODEL_PIVOT",
            "Ollama / pivot",
            _env("OLLAMA_MODEL_PIVOT", "(not set)"),
        ),
        RuntimeConfigEntry(
            "OLLAMA_MODEL_REPORT",
            "Ollama / report",
            _env("OLLAMA_MODEL_REPORT", "(not set)"),
        ),
        RuntimeConfigEntry(
            "GROQ_API_KEY",
            "Groq fallback key",
            _flag("GROQ_API_KEY"),
            is_secret=True,
        ),
        RuntimeConfigEntry(
            "GROQ_MODEL",
            "Groq model",
            _env("GROQ_MODEL", "llama-3.3-70b-versatile"),
        ),
    ]
    return RuntimeConfigSnapshot(paths=paths, ai_backend=ai_backend)
