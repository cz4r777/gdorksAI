import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.events import KIND_ROUTES_MOUNTED, KIND_STARTUP, LEVEL_INFO, record
from app.core.readiness import run_startup_readiness
from app.web import router as web_router


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
        try:
            await run_startup_readiness()
        except Exception:  # noqa: BLE001 — diagnostics must never break boot
            pass
    yield


app = FastAPI(title="gdorksAI", version="0.1.0-alpha.1", lifespan=lifespan)
app.include_router(web_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
