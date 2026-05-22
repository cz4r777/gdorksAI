from fastapi import FastAPI

from app.web import router as web_router

app = FastAPI(title="gdorksAI", version="0.0.1")
app.include_router(web_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
