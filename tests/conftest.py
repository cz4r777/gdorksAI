import pytest


@pytest.fixture(autouse=True)
def _skip_startup_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the lifespan startup readiness probe in every test.

    The probe runs an HTTP call to Ollama and a battery of file-system
    checks; per-test those are noisy and would couple unrelated tests to
    network availability. Tests for readiness itself opt back in.
    """
    monkeypatch.setenv("GDORKSAI_SKIP_STARTUP_READINESS", "1")
