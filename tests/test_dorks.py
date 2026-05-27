import json
from pathlib import Path

import pytest

from app.core.dorks import (
    DorkNotFoundError,
    DorkRegistry,
    InvalidTargetError,
    RegistryError,
    load_default_registry,
)
from app.core.scope import OutOfScopeError, ScopeGuard


def _seed_corpus(root: Path) -> None:
    sqli = root / "SQLi"
    sqli.mkdir()
    (sqli / "basic.txt").write_text(
        "\n".join(
            [
                "# Comment line, skipped",
                "site:{target} inurl:id=",
                "",
                'site:{target} "sql syntax error"',
            ]
        ),
        encoding="utf-8",
    )
    xss = root / "XSS"
    xss.mkdir()
    (xss / "reflected.txt").write_text(
        'site:{target} inurl:"q="\n',
        encoding="utf-8",
    )
    (root / "dorks.json").write_text(
        json.dumps(
            [
                {
                    "category": "GraphQL endpoints",
                    "queries": [
                        "site:{target} inurl:/graphql",
                        "  ",
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )


def _make_scope(root: Path, targets: list[str]) -> ScopeGuard:
    scope_file = root / "scope.json"
    scope_file.write_text(json.dumps({"targets": targets}), encoding="utf-8")
    return ScopeGuard(scope_file)


@pytest.fixture
def permissive_scope(tmp_path: Path) -> ScopeGuard:
    return _make_scope(tmp_path, ["example.com", "*.example.com"])


def test_load_empty_when_path_missing(tmp_path: Path) -> None:
    reg = DorkRegistry.from_path(tmp_path / "does-not-exist")
    assert len(reg) == 0
    assert reg.list_categories() == []


def test_load_corpus(tmp_path: Path) -> None:
    _seed_corpus(tmp_path)
    reg = DorkRegistry.from_path(tmp_path)
    assert len(reg) == 4
    assert reg.list_categories() == ["GraphQL endpoints", "SQLi", "XSS"]


def test_search_by_keyword(tmp_path: Path) -> None:
    _seed_corpus(tmp_path)
    reg = DorkRegistry.from_path(tmp_path)
    hits = reg.search(q="graphql")
    assert len(hits) == 1
    assert hits[0].category == "GraphQL endpoints"


def test_search_by_category(tmp_path: Path) -> None:
    _seed_corpus(tmp_path)
    reg = DorkRegistry.from_path(tmp_path)
    hits = reg.search(category="SQLi")
    assert len(hits) == 2
    assert all(r.category == "SQLi" for r in hits)


def test_search_combined(tmp_path: Path) -> None:
    _seed_corpus(tmp_path)
    reg = DorkRegistry.from_path(tmp_path)
    hits = reg.search(q="syntax", category="SQLi")
    assert len(hits) == 1


def test_render_substitutes_target(
    tmp_path: Path, permissive_scope: ScopeGuard
) -> None:
    _seed_corpus(tmp_path)
    reg = DorkRegistry.from_path(tmp_path)
    record = next(
        r for r in reg.search(category="SQLi") if "inurl:id=" in r.query
    )
    rendered = reg.render(record.id, "example.com", scope_guard=permissive_scope)
    assert rendered == "site:example.com inurl:id="


def test_render_rejects_empty_target(
    tmp_path: Path, permissive_scope: ScopeGuard
) -> None:
    _seed_corpus(tmp_path)
    reg = DorkRegistry.from_path(tmp_path)
    record = reg.search()[0]
    with pytest.raises(InvalidTargetError):
        reg.render(record.id, "", scope_guard=permissive_scope)
    with pytest.raises(InvalidTargetError):
        reg.render(record.id, "   ", scope_guard=permissive_scope)


def test_render_refuses_out_of_scope(tmp_path: Path) -> None:
    _seed_corpus(tmp_path)
    reg = DorkRegistry.from_path(tmp_path)
    scope = _make_scope(tmp_path, ["allowed.com"])
    record = reg.search()[0]
    with pytest.raises(OutOfScopeError):
        reg.render(record.id, "victim.com", scope_guard=scope)


def test_render_unknown_dork_raises(
    tmp_path: Path, permissive_scope: ScopeGuard
) -> None:
    _seed_corpus(tmp_path)
    reg = DorkRegistry.from_path(tmp_path)
    with pytest.raises(DorkNotFoundError):
        reg.render(
            "nope/nothing#1", "example.com", scope_guard=permissive_scope
        )


def test_malformed_json_catalog(tmp_path: Path) -> None:
    (tmp_path / "dorks.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RegistryError):
        DorkRegistry.from_path(tmp_path)


def test_catalog_must_be_list(tmp_path: Path) -> None:
    (tmp_path / "dorks.json").write_text(
        json.dumps({"category": "x", "queries": []}), encoding="utf-8"
    )
    with pytest.raises(RegistryError):
        DorkRegistry.from_path(tmp_path)


def test_load_default_registry_uses_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_corpus(tmp_path)
    monkeypatch.setenv("DORKS_DATA_PATH", str(tmp_path))
    reg = load_default_registry()
    assert len(reg) == 4
