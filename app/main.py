import contextlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.core.events import KIND_ROUTES_MOUNTED, KIND_STARTUP, LEVEL_INFO, record
from app.core.readiness import run_startup_readiness
from app.web import router as web_router


def _load_local_dotenv() -> None:
    """Best-effort .env loader for local runs.

    The app uses ``os.environ`` directly across the codebase, so local
    development needs a small bootstrap step to honor the repo's ``.env``
    file when the operator starts uvicorn without ``--env-file``.
    For this local single-app workflow, the repo's ``.env`` is treated as
    the source of truth so stale shell-level exports do not silently break
    the running app.
    """
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ[key] = value


_load_local_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    record(
        KIND_STARTUP,
        "app",
        f"gdorksAI {app.version} starting",
        level=LEVEL_INFO,
        title=app.title,
        version=app.version,
    )
    route_paths = sorted({getattr(r, "path", "") for r in app.routes if getattr(r, "path", "")})
    record(
        KIND_ROUTES_MOUNTED,
        "web",
        f"{len(route_paths)} routes mounted",
        level=LEVEL_INFO,
        routes=route_paths,
    )
    # Run a startup readiness pass unless explicitly disabled (e.g. in tests
    # where probing Ollama on every TestClient init would be noisy).
    if os.environ.get("GDORKSAI_SKIP_STARTUP_READINESS") != "1":
        # Diagnostics must never break boot.
        with contextlib.suppress(Exception):
            await run_startup_readiness()
    yield


app = FastAPI(title="gdorksAI", version="0.1.0-alpha.2", lifespan=lifespan)
app.include_router(web_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
