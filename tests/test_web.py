import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import web
from app.core import scope as scope_module
from app.main import app


def _seed_minimal_corpus(root: Path) -> None:
    cat = root / "SQLi"
    cat.mkdir()
    (cat / "basic.txt").write_text(
        "site:{target} inurl:id=\n",
        encoding="utf-8",
    )


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> TestClient:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    _seed_minimal_corpus(corpus)

    scope_file = tmp_path / "scope.json"
    scope_file.write_text(
        json.dumps({"targets": ["example.com"]}), encoding="utf-8"
    )

    monkeypatch.setenv("DORKS_DATA_PATH", str(corpus))
    monkeypatch.setenv("SCOPE_FILE", str(scope_file))
    web.reset_registry()
    scope_module.reset_default_guard()
    return TestClient(app)


def test_home_returns_html_with_categories(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "SQLi" in r.text
    assert "<html" in r.text.lower()


def test_search_returns_partial(client: TestClient) -> None:
    r = client.get("/search", params={"q": "inurl"})
    assert r.status_code == 200
    body = r.text
    assert "inurl:id=" in body
    assert "<html" not in body.lower()
    assert "<body" not in body.lower()


def test_search_partial_for_category(client: TestClient) -> None:
    r = client.get("/search", params={"category": "SQLi"})
    assert r.status_code == 200
    assert "inurl:id=" in r.text


def test_search_no_matches(client: TestClient) -> None:
    r = client.get("/search", params={"q": "zzzzznomatch"})
    assert r.status_code == 200
    assert "No matches" in r.text


def test_render_success_returns_google_url(client: TestClient) -> None:
    record = web.get_registry().search()[0]
    r = client.post(
        "/render",
        data={"dork_id": record.id, "target": "example.com"},
    )
    assert r.status_code == 200
    body = r.text
    assert "google.com/search" in body
    assert "example.com" in body
    assert 'target="_blank"' in body
    assert 'rel="noopener noreferrer"' in body


def test_render_refused_out_of_scope(client: TestClient) -> None:
    record = web.get_registry().search()[0]
    r = client.post(
        "/render",
        data={"dork_id": record.id, "target": "evil.com"},
    )
    assert r.status_code == 403
    assert "out of scope" in r.text.lower()
    assert "google.com/search" not in r.text


def test_render_unknown_dork_id(client: TestClient) -> None:
    r = client.post(
        "/render",
        data={"dork_id": "nope/missing#1", "target": "example.com"},
    )
    assert r.status_code == 404
    assert "unknown dork id" in r.text.lower()


def test_render_empty_target(client: TestClient) -> None:
    record = web.get_registry().search()[0]
    r = client.post(
        "/render",
        data={"dork_id": record.id, "target": "   "},
    )
    assert r.status_code == 400
    assert "invalid target" in r.text.lower()


def test_healthz_still_works(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
