"""Session persistence.

After /report generates a Markdown writeup for an authorized engagement,
the result is saved under ``runtime/sessions/<id>/`` so the operator
has a durable artifact. The Phase 3 exit criterion requires that a full
recon-session round-trip produce a saved report file.

Layout
------
::

    runtime/sessions/
        <id>/
            report.md          # the generated Markdown
            meta.json          # {target, backend, prompt_filename,
                               #  prompt_hash, ts}

The ``id`` is the UTC timestamp ``YYYYMMDD-HHMMSS`` plus a short random
suffix so concurrent saves don't collide.

Privacy
-------
Session files contain ONLY what the operator pasted + the AI's
Markdown response. The metadata file carries the same metadata fields
used in the events log (no scope contents, no secrets). The whole tree
sits under ``runtime/`` which is gitignored.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.events import KIND_SESSION_SAVED, LEVEL_INFO, record

_DEFAULT_DIR = "runtime/sessions"
_ENV_KEY = "SESSIONS_DIR"


@dataclass(frozen=True)
class SavedSession:
    session_id: str
    directory: Path
    report_path: Path
    meta_path: Path


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    directory: Path
    report_path: Path
    meta_path: Path
    ts: str
    target: str
    backend: str
    prompt_filename: str


def list_sessions(limit: int | None = None) -> list[SessionSummary]:
    """Return saved session summaries, newest-first.

    Sorted by directory mtime descending. A session whose meta.json is
    missing or malformed is skipped silently — the events file remains
    the source of truth.
    """
    root = sessions_dir()
    if not root.is_dir():
        return []
    out: list[SessionSummary] = []
    children = [p for p in root.iterdir() if p.is_dir()]
    children.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for d in children:
        meta_path = d / "meta.json"
        report_path = d / "report.md"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        out.append(
            SessionSummary(
                session_id=str(meta.get("session_id", d.name)),
                directory=d,
                report_path=report_path,
                meta_path=meta_path,
                ts=str(meta.get("ts", "")),
                target=str(meta.get("target", "")),
                backend=str(meta.get("backend", "")),
                prompt_filename=str(meta.get("prompt_filename", "")),
            )
        )
        if limit is not None and len(out) >= limit:
            break
    return out


def sessions_dir() -> Path:
    return Path(os.environ.get(_ENV_KEY, _DEFAULT_DIR))


def _new_session_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    suffix = secrets.token_hex(2)
    return f"{stamp}-{suffix}"


def save_report(
    *,
    target: str,
    markdown: str,
    backend: str,
    prompt_filename: str,
    prompt_hash: str,
) -> SavedSession:
    """Persist a /report result to disk + emit a session_saved event."""
    session_id = _new_session_id()
    root = sessions_dir() / session_id
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / "report.md"
    meta_path = root / "meta.json"
    report_path.write_text(markdown, encoding="utf-8")
    meta = {
        "session_id": session_id,
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": target,
        "backend": backend,
        "prompt_filename": prompt_filename,
        "prompt_hash": prompt_hash,
        "report_path": str(report_path),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    record(
        KIND_SESSION_SAVED,
        "sessions",
        f"report saved: {session_id}",
        level=LEVEL_INFO,
        session_id=session_id,
        directory=str(root),
        target=target,
        backend=backend,
        prompt_filename=prompt_filename,
        prompt_hash_prefix=prompt_hash[:12],
    )
    return SavedSession(
        session_id=session_id,
        directory=root,
        report_path=report_path,
        meta_path=meta_path,
    )
