from fastapi import FastAPI

from app.capabilities import build_state, compute_menu


def _empty_app() -> FastAPI:
    return FastAPI()


def _phase1_app() -> FastAPI:
    app = FastAPI()

    @app.get("/")
    def home() -> str:
        return "home"

    @app.get("/search")
    def search() -> str:
        return "s"

    @app.post("/render")
    def render() -> str:
        return "r"

    return app


def _phase2_app() -> FastAPI:
    app = _phase1_app()

    @app.get("/query")
    def query() -> str:
        return "q"

    @app.post("/triage")
    def triage() -> str:
        return "t"

    return app


def _phase3_app() -> FastAPI:
    app = _phase2_app()

    @app.get("/pivot")
    def pivot() -> str:
        return "p"

    return app


def test_compute_menu_lists_all_stages_even_when_unavailable() -> None:
    menu = compute_menu(_empty_app())
    ids = [m["id"] for m in menu]
    assert ids == [
        "home",
        "diagnostics",
        "status",
        "query",
        "triage",
        "pivot",
        "report",
        "sessions",
    ]
    assert all(m["available"] is False for m in menu)


def test_compute_menu_home_available_when_route_mounted() -> None:
    menu = compute_menu(_phase1_app())
    by_id = {m["id"]: m for m in menu}
    assert by_id["home"]["available"] is True
    assert by_id["query"]["available"] is False
    assert by_id["status"]["available"] is False


def test_compute_menu_phase2_available_when_routes_mounted() -> None:
    menu = compute_menu(_phase2_app())
    by_id = {m["id"]: m for m in menu}
    assert by_id["home"]["available"] is True
    assert by_id["query"]["available"] is True
    assert by_id["triage"]["available"] is True
    assert by_id["pivot"]["available"] is False


def test_build_state_bootstrap_when_home_missing() -> None:
    assert build_state(compute_menu(_empty_app())) == "bootstrap"


def test_build_state_phase1_when_home_only() -> None:
    assert build_state(compute_menu(_phase1_app())) == "phase-1"


def test_build_state_phase2_when_any_phase2_route() -> None:
    assert build_state(compute_menu(_phase2_app())) == "phase-2"


def test_build_state_phase3_when_any_phase3_route() -> None:
    assert build_state(compute_menu(_phase3_app())) == "phase-3"


def test_menu_phase_strings_are_canonical() -> None:
    """Catch typos in the stage table."""
    menu = compute_menu(_empty_app())
    for item in menu:
        assert item["phase"] in {"1", "2", "3"}
        assert item["label"]
        assert item["hint"]
        assert item["path"].startswith("/")
