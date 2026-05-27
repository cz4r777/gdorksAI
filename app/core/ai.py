"""Local-first AI adapter.

Single interface for all AI calls in the app. Routes to Ollama (localhost)
by default; falls back to Groq only when Ollama is unreachable / the
requested model is missing AND ``GROQ_API_KEY`` is set. No silent
degradation: failures surface as :class:`AIAdapterError` with a typed
``reason``.

Per-call rails:

1. ``scope_guard.assert_in_scope(target)`` before any backend call.
2. Prompt file looked up under ``app/core/prompts/<role>_v<n>.md``;
   filename + sha256 of rendered content recorded on every call.
3. Backend call (async httpx).
4. Post-call hostname scan against the scope. Any domain in the model
   output that is not in scope -> refuse the entire response with
   ``OUT_OF_SCOPE_OUTPUT``.

Telemetry is off by default (no outbound metrics). Refusals are logged
to the ``gdorksai.ai`` logger at WARNING.

Public surface
--------------
* :class:`AIAdapter` — class form for tests / DI
* :func:`load_default_adapter` — lazy adapter from env
* :func:`reset_default_adapter` — test helper
* :class:`AIRequest`, :class:`AIResponse`
* :class:`AIAdapterError` with :class:`AIErrorReason`
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx

from app.core.events import (
    KIND_AI_CALL,
    KIND_AI_REFUSED,
    LEVEL_INFO,
    LEVEL_WARN,
    record,
)
from app.core.scope import OutOfScopeError, ScopeGuard

_log = logging.getLogger("gdorksai.ai")

_PROMPTS_DIR_DEFAULT = Path("app/core/prompts")
_SYSTEM_MARKER = "---SYSTEM---"
_USER_MARKER = "---USER---"

# Match plausible hostnames inside model output. Conservative: at least one
# dot, ASCII alnum + hyphens per label, 2+ char TLD. Used for the post-call
# scope scan, not for input validation.
_HOSTNAME_RE = re.compile(
    r"\b(?=[a-zA-Z0-9.-]{4,253}\b)"
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,}\b"
)


class AIErrorReason(StrEnum):
    OLLAMA_UNREACHABLE = "ollama_unreachable"
    OLLAMA_MODEL_MISSING = "ollama_model_missing"
    OLLAMA_HTTP_ERROR = "ollama_http_error"
    GROQ_NOT_CONFIGURED = "groq_not_configured"
    GROQ_RATE_LIMITED = "groq_rate_limited"
    GROQ_HTTP_ERROR = "groq_http_error"
    OUT_OF_SCOPE_OUTPUT = "out_of_scope_output"
    PROMPT_NOT_FOUND = "prompt_not_found"
    MALFORMED_RESPONSE = "malformed_response"
    NO_BACKEND_AVAILABLE = "no_backend_available"


class AIAdapterError(Exception):
    """Adapter error with a typed reason. ``cause`` is the underlying exception if any."""

    def __init__(
        self,
        reason: AIErrorReason,
        message: str = "",
        *,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message or reason.value)
        self.reason = reason
        self.cause = cause


@dataclass(frozen=True)
class AIRequest:
    role: str
    target: str
    user_input: str
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AIResponse:
    text: str
    backend: str
    role: str
    target: str
    prompt_filename: str
    prompt_hash: str


@dataclass(frozen=True)
class _RenderedPrompt:
    filename: str
    sha256: str
    system: str
    user: str


def _render_template(text: str, vars: dict[str, str]) -> str:
    out = text
    for k, v in vars.items():
        out = out.replace("{" + k + "}", v)
    return out


def _load_prompt(role: str, prompts_dir: Path, vars: dict[str, str]) -> _RenderedPrompt:
    # Pick highest-versioned file: <role>_v<n>.md
    candidates = sorted(prompts_dir.glob(f"{role}_v*.md"))
    if not candidates:
        raise AIAdapterError(
            AIErrorReason.PROMPT_NOT_FOUND,
            f"no prompt file for role {role!r} under {prompts_dir}",
        )
    path = candidates[-1]
    raw = path.read_text(encoding="utf-8")
    rendered = _render_template(raw, vars)
    system, user = _split_sections(rendered, path)
    sha = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    return _RenderedPrompt(filename=path.name, sha256=sha, system=system, user=user)


def _split_sections(rendered: str, path: Path) -> tuple[str, str]:
    if _SYSTEM_MARKER not in rendered or _USER_MARKER not in rendered:
        raise AIAdapterError(
            AIErrorReason.MALFORMED_RESPONSE,
            f"prompt {path.name} missing ---SYSTEM--- or ---USER--- marker",
        )
    _, _, after_system = rendered.partition(_SYSTEM_MARKER)
    system, _, user = after_system.partition(_USER_MARKER)
    return system.strip(), user.strip()


def _extract_hostnames(text: str) -> list[str]:
    return _HOSTNAME_RE.findall(text)


class AIAdapter:
    """Routes generate() calls to Ollama first, then Groq if configured."""

    def __init__(
        self,
        *,
        ollama_host: str,
        ollama_models: dict[str, str],
        groq_api_key: str | None,
        groq_model: str,
        prompts_dir: Path,
        scope_guard: ScopeGuard,
        http_client: httpx.AsyncClient | None = None,
        request_timeout: float = 30.0,
    ) -> None:
        self._ollama_host = ollama_host.rstrip("/")
        self._ollama_models = ollama_models
        self._groq_api_key = groq_api_key or None
        self._groq_model = groq_model
        self._prompts_dir = prompts_dir
        self._scope = scope_guard
        self._client = http_client
        self._timeout = request_timeout

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def generate(self, req: AIRequest) -> AIResponse:
        try:
            self._scope.assert_in_scope(
                req.target, caller=f"ai.generate/{req.role}"
            )
        except OutOfScopeError:
            record(
                KIND_AI_REFUSED,
                "ai",
                f"ai refused: target out of scope ({req.role})",
                level=LEVEL_WARN,
                role=req.role,
                reason="out_of_scope_target",
            )
            raise
        try:
            prompt = _load_prompt(
                req.role,
                self._prompts_dir,
                {
                    "target": req.target,
                    "user_input": req.user_input,
                    **req.extra,
                },
            )
        except AIAdapterError as e:
            record(
                KIND_AI_REFUSED,
                "ai",
                f"ai refused: {e.reason.value} ({req.role})",
                level=LEVEL_WARN,
                role=req.role,
                reason=e.reason.value,
            )
            raise
        try:
            text, backend = await self._call_with_fallback(req.role, prompt)
        except AIAdapterError as e:
            record(
                KIND_AI_REFUSED,
                "ai",
                f"ai refused: {e.reason.value} ({req.role})",
                level=LEVEL_WARN,
                role=req.role,
                reason=e.reason.value,
                prompt_filename=prompt.filename,
                prompt_hash_prefix=prompt.sha256[:12],
            )
            raise
        try:
            self._post_call_scope_scan(text, req)
        except AIAdapterError as e:
            record(
                KIND_AI_REFUSED,
                "ai",
                f"ai refused: model output referenced out-of-scope host ({req.role})",
                level=LEVEL_WARN,
                role=req.role,
                reason=e.reason.value,
                backend=backend,
                prompt_filename=prompt.filename,
                prompt_hash_prefix=prompt.sha256[:12],
            )
            raise
        _log.info(
            "ai call: role=%s backend=%s prompt=%s hash=%s",
            req.role,
            backend,
            prompt.filename,
            prompt.sha256[:12],
        )
        record(
            KIND_AI_CALL,
            "ai",
            f"ai call ok: role={req.role} backend={backend}",
            level=LEVEL_INFO,
            role=req.role,
            backend=backend,
            prompt_filename=prompt.filename,
            prompt_hash_prefix=prompt.sha256[:12],
        )
        return AIResponse(
            text=text,
            backend=backend,
            role=req.role,
            target=req.target,
            prompt_filename=prompt.filename,
            prompt_hash=prompt.sha256,
        )

    async def _call_with_fallback(
        self, role: str, prompt: _RenderedPrompt
    ) -> tuple[str, str]:
        try:
            text = await self._call_ollama(role, prompt)
            return text, "ollama"
        except AIAdapterError as e:
            if e.reason not in {
                AIErrorReason.OLLAMA_UNREACHABLE,
                AIErrorReason.OLLAMA_MODEL_MISSING,
            }:
                raise
            if not self._groq_api_key:
                _log.warning(
                    "ollama failed (%s) and GROQ_API_KEY not set — no backend available",
                    e.reason.value,
                )
                raise AIAdapterError(
                    AIErrorReason.NO_BACKEND_AVAILABLE,
                    "ollama failed and groq is not configured",
                    cause=e,
                ) from e
            _log.info("ollama failed (%s); falling back to groq", e.reason.value)
            text = await self._call_groq(prompt)
            return text, "groq"

    async def _call_ollama(self, role: str, prompt: _RenderedPrompt) -> str:
        model = self._ollama_models.get(role)
        if not model:
            raise AIAdapterError(
                AIErrorReason.OLLAMA_MODEL_MISSING,
                f"no ollama model configured for role {role!r}",
            )
        url = f"{self._ollama_host}/api/generate"
        body = {
            "model": model,
            "system": prompt.system,
            "prompt": prompt.user,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        client = await self._get_client()
        try:
            r = await client.post(url, json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            raise AIAdapterError(
                AIErrorReason.OLLAMA_UNREACHABLE,
                f"ollama at {self._ollama_host} unreachable",
                cause=e,
            ) from e
        if r.status_code == 404:
            raise AIAdapterError(
                AIErrorReason.OLLAMA_MODEL_MISSING,
                f"ollama model {model!r} not installed",
            )
        if r.status_code >= 400:
            raise AIAdapterError(
                AIErrorReason.OLLAMA_HTTP_ERROR,
                f"ollama HTTP {r.status_code}",
            )
        try:
            data = r.json()
        except json.JSONDecodeError as e:
            raise AIAdapterError(
                AIErrorReason.MALFORMED_RESPONSE,
                "ollama returned non-JSON",
                cause=e,
            ) from e
        text = data.get("response")
        if not isinstance(text, str):
            raise AIAdapterError(
                AIErrorReason.MALFORMED_RESPONSE,
                "ollama response missing 'response' string",
            )
        return text

    async def _call_groq(self, prompt: _RenderedPrompt) -> str:
        if not self._groq_api_key:
            raise AIAdapterError(
                AIErrorReason.GROQ_NOT_CONFIGURED,
                "GROQ_API_KEY not set",
            )
        url = "https://api.groq.com/openai/v1/chat/completions"
        body: dict[str, Any] = {
            "model": self._groq_model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self._groq_api_key}"}
        client = await self._get_client()
        try:
            r = await client.post(url, json=body, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            raise AIAdapterError(
                AIErrorReason.GROQ_HTTP_ERROR,
                "groq request failed",
                cause=e,
            ) from e
        if r.status_code == 429:
            raise AIAdapterError(
                AIErrorReason.GROQ_RATE_LIMITED,
                "groq rate-limited (429)",
            )
        if r.status_code >= 400:
            raise AIAdapterError(
                AIErrorReason.GROQ_HTTP_ERROR,
                f"groq HTTP {r.status_code}",
            )
        try:
            data = r.json()
        except json.JSONDecodeError as e:
            raise AIAdapterError(
                AIErrorReason.MALFORMED_RESPONSE,
                "groq returned non-JSON",
                cause=e,
            ) from e
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIAdapterError(
                AIErrorReason.MALFORMED_RESPONSE,
                "groq response missing choices",
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise AIAdapterError(
                AIErrorReason.MALFORMED_RESPONSE,
                "groq choice is not an object",
            )
        message = first.get("message")
        if not isinstance(message, dict):
            raise AIAdapterError(
                AIErrorReason.MALFORMED_RESPONSE,
                "groq message is not an object",
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise AIAdapterError(
                AIErrorReason.MALFORMED_RESPONSE,
                "groq message.content is not a string",
            )
        return content

    def _post_call_scope_scan(self, text: str, req: AIRequest) -> None:
        for host in _extract_hostnames(text):
            if not self._scope.is_in_scope(host):
                _log.warning(
                    "ai output refused: role=%s target=%s out_of_scope_host=%s",
                    req.role,
                    req.target,
                    host,
                )
                raise AIAdapterError(
                    AIErrorReason.OUT_OF_SCOPE_OUTPUT,
                    f"model output referenced out-of-scope host {host!r}",
                )


_default_adapter: AIAdapter | None = None


def _models_from_env() -> dict[str, str]:
    return {
        "query_gen": os.environ.get(
            "OLLAMA_MODEL_QUERY", "llama3.1:8b-instruct"
        ),
        "triage": os.environ.get(
            "OLLAMA_MODEL_TRIAGE", "llama3.1:8b-instruct"
        ),
        "pivot": os.environ.get(
            "OLLAMA_MODEL_PIVOT", "llama3.1:8b-instruct"
        ),
        "report": os.environ.get(
            "OLLAMA_MODEL_REPORT", "qwen2.5:14b-instruct"
        ),
    }


def load_default_adapter() -> AIAdapter:
    """Build the lazy default adapter from environment variables."""
    global _default_adapter
    if _default_adapter is None:
        _default_adapter = AIAdapter(
            ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            ollama_models=_models_from_env(),
            groq_api_key=os.environ.get("GROQ_API_KEY") or None,
            groq_model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            prompts_dir=Path(
                os.environ.get("PROMPTS_DIR", str(_PROMPTS_DIR_DEFAULT))
            ),
            scope_guard=ScopeGuard(),
        )
    return _default_adapter


def reset_default_adapter() -> None:
    """Test helper. Clears the cached default adapter."""
    global _default_adapter
    _default_adapter = None
