"""Scope guard.

Validates that a target hostname is inside the operator's authorized
engagement scope before any rendered dork can be returned.

Scope file (default ``runtime/scope.json``, override with ``SCOPE_FILE``)::

    {
        "targets": [
            "example.com",         # exact apex
            "*.example.com",       # subdomains only (NOT the apex)
            "research.example.org"
        ]
    }

Rules
-----
* Hostnames are normalized: lower-cased and trailing dot stripped.
* ``*.example.com`` matches ``a.example.com`` and ``a.b.example.com``
  but NOT the apex ``example.com``. Add an explicit ``example.com`` entry
  for the apex.
* Missing scope file => empty scope => refuse all (logged).
* Malformed JSON / wrong shape => empty scope => refuse all (logged).
* Refusals are logged with target, caller label, and scope file path.

Public API
----------
* ``is_in_scope(target)`` -> bool
* ``assert_in_scope(target, *, caller="unknown")`` -> None, raises
  :class:`OutOfScopeError`.
* :class:`ScopeGuard` for tests / dependency injection.
* :class:`OutOfScopeError` is the refusal exception.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

_DEFAULT_SCOPE_FILE = "runtime/scope.json"
_SCOPE_ENV = "SCOPE_FILE"
_log = logging.getLogger("gdorksai.scope")


class OutOfScopeError(Exception):
    """Raised by :func:`assert_in_scope` when a target is not authorized."""


def _normalize(host: str) -> str:
    return host.strip().lower().rstrip(".")


class ScopeGuard:
    """Authorization gate for target hostnames."""

    def __init__(self, scope_file: Path | str | None = None) -> None:
        if scope_file is not None:
            self._path = Path(scope_file)
        else:
            self._path = Path(os.environ.get(_SCOPE_ENV, _DEFAULT_SCOPE_FILE))
        self._exact: frozenset[str] = frozenset()
        self._wildcards: tuple[str, ...] = ()
        self._loaded = False

    @property
    def scope_file(self) -> Path:
        return self._path

    def _load(self) -> None:
        if self._loaded:
            return
        exact: set[str] = set()
        wildcards: list[str] = []
        data: object = None
        if not self._path.is_file():
            _log.warning(
                "scope file missing: %s — refusing all targets", self._path
            )
        else:
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                _log.warning(
                    "scope file unreadable %s: %s — refusing all",
                    self._path,
                    e,
                )
                data = None
        if isinstance(data, dict):
            targets = data.get("targets", [])
            if isinstance(targets, list):
                for item in targets:
                    host = _normalize(str(item))
                    if not host:
                        continue
                    if host.startswith("*."):
                        suffix = host[2:]
                        if suffix:
                            wildcards.append(suffix)
                    else:
                        exact.add(host)
            else:
                _log.warning(
                    "scope.targets must be a list in %s — refusing all",
                    self._path,
                )
        elif data is not None:
            _log.warning(
                "scope file must be a JSON object in %s — refusing all",
                self._path,
            )
        self._exact = frozenset(exact)
        self._wildcards = tuple(wildcards)
        self._loaded = True

    def is_in_scope(self, target: str) -> bool:
        self._load()
        host = _normalize(target)
        if not host:
            return False
        if host in self._exact:
            return True
        return any(host.endswith("." + suffix) for suffix in self._wildcards)

    def assert_in_scope(self, target: str, *, caller: str = "unknown") -> None:
        if not self.is_in_scope(target):
            _log.warning(
                "scope refused: target=%r caller=%r scope_file=%s",
                target,
                caller,
                self._path,
            )
            raise OutOfScopeError(f"target out of scope: {target!r}")

    def add_target(self, target: str) -> bool:
        """Append a target to the scope file and refresh the in-memory state.

        Returns True if the target was added, False if it was already
        present (idempotent). Creates the parent directory and the file
        with a fresh ``{"targets": []}`` structure if either is missing.

        This is the operator-facing "Authorize" path used by the UI 403
        block. The button click IS the authorization — same security
        model, just one click instead of editing JSON.
        """
        host = _normalize(target)
        if not host:
            raise ValueError("target is empty")
        self._load()
        if host.startswith("*."):
            suffix = host[2:]
            if suffix in self._wildcards:
                return False
        elif host in self._exact:
            return False
        # Read current file (or treat missing as {})
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        targets = raw.get("targets")
        if not isinstance(targets, list):
            targets = []
        if host not in [str(t).strip().lower() for t in targets]:
            targets.append(host)
        raw["targets"] = targets
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(raw, indent=2) + "\n", encoding="utf-8"
        )
        # Reset cached parse so the next is_in_scope() picks up the new entry.
        self._loaded = False
        return True


_default_guard: ScopeGuard | None = None


def _get_default_guard() -> ScopeGuard:
    global _default_guard
    if _default_guard is None:
        _default_guard = ScopeGuard()
    return _default_guard


def is_in_scope(target: str) -> bool:
    return _get_default_guard().is_in_scope(target)


def assert_in_scope(target: str, *, caller: str = "unknown") -> None:
    _get_default_guard().assert_in_scope(target, caller=caller)


def reset_default_guard() -> None:
    """Force the next call to rebuild the default guard.

    Test helper. Use after ``monkeypatch.setenv("SCOPE_FILE", ...)``.
    """
    global _default_guard
    _default_guard = None
