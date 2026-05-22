"""Dork registry.

Loads a dork corpus from a directory pointed at by ``DORKS_DATA_PATH``,
normalizes per-category text files (and an optional flat JSON catalog)
into immutable records, and exposes category listing, search, and
target-substituted query rendering.

Phase 1 scope: parsing + in-memory index + render helper. Scope-guard
integration is P1-T2; web UI is P1-T3.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_TARGET_PLACEHOLDER = "{target}"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class RegistryError(Exception):
    """Base for registry errors."""


class DorkNotFoundError(RegistryError):
    """Raised when ``render`` is called with an unknown ``dork_id``."""


class InvalidTargetError(RegistryError):
    """Raised when ``render`` is called with an empty/whitespace target."""


@dataclass(frozen=True)
class DorkRecord:
    id: str
    category: str
    query: str
    source_file: str


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value.lower()).strip("-")


class DorkRegistry:
    """In-memory dork registry built from a corpus directory."""

    def __init__(self, records: list[DorkRecord]) -> None:
        self._records: list[DorkRecord] = records
        self._by_id: dict[str, DorkRecord] = {r.id: r for r in records}

    @classmethod
    def from_path(cls, root: Path | str) -> DorkRegistry:
        """Load a registry from a corpus directory.

        Expected layout:
        - subdirectories named per category, containing ``.txt`` files with
          one dork per line. Blank lines and lines starting with ``#`` are
          skipped.
        - optional flat catalog at ``<root>/dorks.json`` with shape
          ``[{"category": str, "queries": [str, ...]}, ...]``.

        A missing root directory yields an empty registry. A malformed JSON
        catalog raises :class:`RegistryError`.
        """
        root_path = Path(root)
        if not root_path.exists():
            return cls([])
        records: list[DorkRecord] = list(cls._load_from_dirs(root_path))
        catalog = root_path / "dorks.json"
        if catalog.is_file():
            records.extend(cls._load_from_json(catalog))
        return cls(records)

    @staticmethod
    def _load_from_dirs(root: Path) -> Iterable[DorkRecord]:
        for category_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            category = category_dir.name
            for txt in sorted(category_dir.glob("*.txt")):
                source = str(txt.relative_to(root))
                with txt.open("r", encoding="utf-8", errors="replace") as f:
                    for line_no, raw in enumerate(f, start=1):
                        query = raw.strip()
                        if not query or query.startswith("#"):
                            continue
                        rid = f"{_slug(category)}/{_slug(txt.stem)}#{line_no}"
                        yield DorkRecord(
                            id=rid,
                            category=category,
                            query=query,
                            source_file=source,
                        )

    @staticmethod
    def _load_from_json(path: Path) -> Iterable[DorkRecord]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise RegistryError(f"malformed dork catalog: {path}: {e}") from e
        if not isinstance(data, list):
            raise RegistryError(f"dork catalog must be a list: {path}")
        source = path.name
        for cat_idx, entry in enumerate(data):
            if not isinstance(entry, dict):
                raise RegistryError(f"catalog entry {cat_idx} is not an object")
            category = str(entry.get("category", ""))
            queries = entry.get("queries", [])
            if not isinstance(queries, list):
                raise RegistryError(
                    f"catalog entry {cat_idx} 'queries' must be a list"
                )
            for q_idx, q in enumerate(queries):
                query = str(q).strip()
                if not query:
                    continue
                rid = f"json/{_slug(category)}#{cat_idx}.{q_idx}"
                yield DorkRecord(
                    id=rid,
                    category=category,
                    query=query,
                    source_file=source,
                )

    def __len__(self) -> int:
        return len(self._records)

    def list_categories(self) -> list[str]:
        return sorted({r.category for r in self._records})

    def search(
        self,
        q: str | None = None,
        category: str | None = None,
    ) -> list[DorkRecord]:
        q_lower = q.lower() if q else None
        out: list[DorkRecord] = []
        for r in self._records:
            if category is not None and r.category != category:
                continue
            if q_lower is not None and q_lower not in r.query.lower():
                continue
            out.append(r)
        return out

    def get(self, dork_id: str) -> DorkRecord:
        try:
            return self._by_id[dork_id]
        except KeyError as e:
            raise DorkNotFoundError(dork_id) from e

    def render(self, dork_id: str, target: str) -> str:
        if not target or not target.strip():
            raise InvalidTargetError("target is required")
        record = self.get(dork_id)
        return record.query.replace(_TARGET_PLACEHOLDER, target.strip())


def load_default_registry() -> DorkRegistry:
    """Load a registry using ``DORKS_DATA_PATH`` from the environment.

    Defaults to ``data/dorks`` if the env var is not set.
    """
    path = os.environ.get("DORKS_DATA_PATH", "data/dorks")
    return DorkRegistry.from_path(path)
