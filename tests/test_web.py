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
    monkeypatch.setenv("EVENTS_FILE", str(tmp_path / "events.jsonl"))
    web.reset_registry()
    scope_module.reset_default_guard()
    return TestClient(app)


def test_home_returns_html_with_categories(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "SQLi" in r.text
    assert "<html" in r.text.lower()


def test_home_search_box_has_category_dropdown(client: TestClient) -> None:
    """The search box must surface a category dropdown so the operator can
    see every available group of dorks at a glance."""
    r = client.get("/")
    body = r.text
    # The select element exists alongside the search input
    assert '<select' in body
    assert 'id="q-category"' in body
    assert 'name="category"' in body
    # Default option lists category count
    assert "All categories (" in body
    # Every category appears as an option
    assert '<option value="SQLi">SQLi</option>' in body
    # The dropdown is wired to /search via HTMX
    assert 'hx-get="/search"' in body
    # Search input includes the category from the dropdown
    assert 'hx-include="#q-category"' in body


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


def test_home_renders_navigation_with_phase_state(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert 'data-testid="primary-nav"' in body
    # /pivot is mounted via P3-T1 on this branch, so build_state flips to phase-3.
    assert 'data-build-state="phase-3"' in body
    assert 'data-stage="home"' in body
    assert 'data-stage="query"' in body
    assert 'data-stage="status"' in body


def test_home_marks_phase1_stages_available(client: TestClient) -> None:
    r = client.get("/")
    body = r.text
    assert 'data-stage="home"' in body and 'data-available="true"' in body


def test_home_marks_all_stages_available_after_a2(client: TestClient) -> None:
    """Once /report mounts (A2), every menu stage is real — no 'coming soon'."""
    r = client.get("/")
    body = r.text
    assert "coming soon" not in body.lower()
    for stage in (
        "home",
        "diagnostics",
        "status",
        "query",
        "triage",
        "pivot",
        "report",
    ):
        assert f'data-stage="{stage}"' in body
    # No aria-disabled stages remain
    assert 'aria-disabled="true"' not in body


def test_diagnostics_page_renders_empty_when_no_events(client: TestClient) -> None:
    r = client.get("/diagnostics")
    assert r.status_code == 200
    assert "Diagnostics" in r.text
    # Lifespan-emitted startup events should already exist
    assert "startup" in r.text or "No events yet" in r.text


def test_diagnostics_refresh_runs_health_and_returns_partial(
    client: TestClient,
) -> None:
    r = client.post("/diagnostics/refresh")
    assert r.status_code == 200
    body = r.text
    assert "<html" not in body.lower()
    assert "events-table" in body
    assert "health" in body or "ollama" in body


def test_diagnostics_jsonl_streams_raw_file(client: TestClient) -> None:
    # Cause some events to be written
    client.post("/diagnostics/refresh")
    r = client.get("/diagnostics.jsonl")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    # Each line should be valid JSON
    for line in r.text.splitlines():
        if not line.strip():
            continue
        json.loads(line)


def test_nav_includes_diagnostics(client: TestClient) -> None:
    r = client.get("/")
    assert 'data-stage="diagnostics"' in r.text
    assert 'data-available="true"' in r.text  # /diagnostics IS mounted


def test_status_page_renders(client: TestClient) -> None:
    r = client.get("/status")
    assert r.status_code == 200
    body = r.text
    assert "Status" in body
    # No probes have been triggered through the web layer yet beyond lifespan
    # events, so component cards should show as "not yet observed" or "ok".
    assert 'data-component="ollama"' in body
    assert 'data-component="groq"' in body
    assert 'data-component="registry"' in body
    assert 'data-component="scope"' in body
    assert 'data-component="prompts"' in body


def test_status_refresh_returns_partial_with_probes(client: TestClient) -> None:
    r = client.post("/status/refresh")
    assert r.status_code == 200
    body = r.text
    # Partial — should not include <html>
    assert "<html" not in body.lower()
    assert 'id="status-cards"' in body
    # After running probes at least one component card has a level badge
    assert "data-level=" in body


def test_status_route_is_now_in_nav(client: TestClient) -> None:
    r = client.get("/")
    body = r.text
    # /status is mounted now, so the menu should mark it available
    assert 'data-stage="status"' in body
    # The "status" stage block should include data-available="true"
    import re

    m = re.search(
        r'data-stage="status"\s+data-available="(true|false)"', body
    )
    assert m is not None
    assert m.group(1) == "true"


def test_home_shows_category_counts(client: TestClient) -> None:
    r = client.get("/")
    body = r.text
    # Category card shows count next to name
    assert "SQLi" in body
    assert "(1)" in body  # _seed_minimal_corpus puts exactly 1 dork in SQLi
    # The total dorks summary is rendered
    assert "1 total dorks" in body
    # And a link to /dorks exists
    assert 'href="/dorks"' in body


def test_home_categories_link_to_category_page(client: TestClient) -> None:
    r = client.get("/")
    body = r.text
    assert 'href="/category/SQLi"' in body
    assert 'data-category="SQLi"' in body


def test_category_page_renders_grouped(client: TestClient) -> None:
    r = client.get("/category/SQLi")
    assert r.status_code == 200
    body = r.text
    # Breadcrumb to home
    assert 'href="/"' in body
    # Source-file group header
    assert "basic.txt" in body
    # Dork query content
    assert "inurl:id=" in body
    # Render form exists
    assert 'hx-post="/render"' in body


def test_unknown_category_returns_404(client: TestClient) -> None:
    r = client.get("/category/NoSuchCategory")
    assert r.status_code == 404
    assert "Unknown category" in r.text


def test_dorks_paginated_list(client: TestClient) -> None:
    r = client.get("/dorks")
    assert r.status_code == 200
    body = r.text
    assert "All dorks" in body
    assert "inurl:id=" in body
    # Each dork links back to its category
    assert 'href="/category/SQLi"' in body


def test_dorks_pagination_caps_per(client: TestClient) -> None:
    # per is capped at 200; even an absurd value doesn't break the page
    r = client.get("/dorks", params={"per": 99999})
    assert r.status_code == 200
    assert "All dorks" in r.text


def test_dorks_page_below_one_normalized(client: TestClient) -> None:
    r = client.get("/dorks", params={"page": -3})
    assert r.status_code == 200
    assert "page 1" in r.text
