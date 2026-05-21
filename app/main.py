from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="gdorksAI", version="0.0.1")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (
        "<!doctype html><html><head><title>gdorksAI</title></head>"
        "<body><h1>gdorksAI</h1>"
        "<p>Framework bootstrap. See docs/ for architecture and roadmap.</p>"
        "</body></html>"
    )
