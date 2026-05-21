import json
import logging
from pathlib import Path

import pytest

from app.core import scope as scope_module
from app.core.scope import OutOfScopeError, ScopeGuard


def _write_scope(path: Path, targets: list[str]) -> None:
    path.write_text(json.dumps({"targets": targets}), encoding="utf-8")


def test_exact_host_in_scope(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["example.com"])
    guard = ScopeGuard(scope_file)
    assert guard.is_in_scope("example.com") is True


def test_exact_host_out_of_scope(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["example.com"])
    guard = ScopeGuard(scope_file)
    assert guard.is_in_scope("evil.com") is False


def test_wildcard_matches_subdomain(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["*.example.com"])
    guard = ScopeGuard(scope_file)
    assert guard.is_in_scope("a.example.com") is True
    assert guard.is_in_scope("a.b.example.com") is True


def test_wildcard_does_not_match_apex(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["*.example.com"])
    guard = ScopeGuard(scope_file)
    assert guard.is_in_scope("example.com") is False


def test_apex_entry_does_not_imply_subdomain(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["example.com"])
    guard = ScopeGuard(scope_file)
    assert guard.is_in_scope("api.example.com") is False


def test_explicit_apex_plus_wildcard(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["example.com", "*.example.com"])
    guard = ScopeGuard(scope_file)
    assert guard.is_in_scope("example.com") is True
    assert guard.is_in_scope("api.example.com") is True


def test_wildcard_does_not_match_lookalike(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["*.example.com"])
    guard = ScopeGuard(scope_file)
    assert guard.is_in_scope("notexample.com") is False
    assert guard.is_in_scope("xexample.com") is False


def test_hostname_normalization(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["Example.Com.", "*.Internal.Example.com"])
    guard = ScopeGuard(scope_file)
    assert guard.is_in_scope("EXAMPLE.com") is True
    assert guard.is_in_scope("example.com.") is True
    assert guard.is_in_scope("Web.Internal.Example.Com") is True


def test_missing_scope_file_refuses_all(tmp_path: Path) -> None:
    guard = ScopeGuard(tmp_path / "absent.json")
    assert guard.is_in_scope("anything.com") is False
    assert guard.is_in_scope("") is False


def test_malformed_json_refuses_all(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    scope_file.write_text("{ not json", encoding="utf-8")
    guard = ScopeGuard(scope_file)
    assert guard.is_in_scope("example.com") is False


def test_wrong_top_level_shape_refuses_all(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    scope_file.write_text(json.dumps(["example.com"]), encoding="utf-8")
    guard = ScopeGuard(scope_file)
    assert guard.is_in_scope("example.com") is False


def test_targets_must_be_list(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    scope_file.write_text(
        json.dumps({"targets": "example.com"}), encoding="utf-8"
    )
    guard = ScopeGuard(scope_file)
    assert guard.is_in_scope("example.com") is False


def test_empty_target_refuses(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["example.com"])
    guard = ScopeGuard(scope_file)
    assert guard.is_in_scope("") is False
    assert guard.is_in_scope("   ") is False


def test_assert_in_scope_passes_silently(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["example.com"])
    guard = ScopeGuard(scope_file)
    guard.assert_in_scope("example.com")


def test_assert_in_scope_raises_out_of_scope(tmp_path: Path) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["example.com"])
    guard = ScopeGuard(scope_file)
    with pytest.raises(OutOfScopeError):
        guard.assert_in_scope("evil.com")


def test_refusal_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["example.com"])
    guard = ScopeGuard(scope_file)
    with caplog.at_level(logging.WARNING, logger="gdorksai.scope"):
        with pytest.raises(OutOfScopeError):
            guard.assert_in_scope("evil.com", caller="test")
    assert any("scope refused" in r.message for r in caplog.records)
    assert any("evil.com" in r.message for r in caplog.records)


def test_module_level_default_guard_uses_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scope_file = tmp_path / "scope.json"
    _write_scope(scope_file, ["example.com"])
    monkeypatch.setenv("SCOPE_FILE", str(scope_file))
    scope_module.reset_default_guard()
    assert scope_module.is_in_scope("example.com") is True
    assert scope_module.is_in_scope("evil.com") is False
    with pytest.raises(OutOfScopeError):
        scope_module.assert_in_scope("evil.com", caller="t")
    scope_module.reset_default_guard()
