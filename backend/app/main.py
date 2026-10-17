import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app import mcp_server
from app.db import init_db
from app.pipeline.transcribe import warm_up
from app.routes import admin, auth, brand, chat, drafts, health, instagram, internal_wa, media, tokens, whatsapp_link
from app.worker import scheduler
from app.worker.runner import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx logs full request URLs at INFO; Instagram's token calls carry client_secret / access_token in the query
logging.getLogger("httpx").setLevel(logging.WARNING)


class _RedactAccess(logging.Filter):
    """Access lines without query strings (OAuth code/state) or signed media tokens."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            path = str(record.args[2]).split("?", 1)[0]
            if path.startswith("/media/"):
                path = "/media/<token>"
            record.args = (*record.args[:2], path, *record.args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactAccess())
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.is_prod and settings.weak_secrets:
        raise RuntimeError(f"ENV=prod but these are unset or dev defaults: {', '.join(settings.weak_secrets).upper()}")
    Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
    await init_db()
    worker = Worker()
    tasks = [asyncio.create_task(worker.run()), asyncio.create_task(scheduler.loop())]
    asyncio.get_running_loop().run_in_executor(None, warm_up)  # load Whisper before the first video
    log.info("%s started (env=%s, base=%s)", settings.app_name, settings.env, settings.app_base_url)
    try:
        async with mcp_server.mcp.session_manager.run():
            yield
    finally:
        worker.stop()
        for task in tasks:
            task.cancel()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
for router in (health.router, auth.router, whatsapp_link.router, instagram.router, brand.router, drafts.router,
               chat.router, media.router, admin.router, internal_wa.router, tokens.router):
    app.include_router(router)

app.add_route("/mcp", mcp_server.mcp_root)  # exact path; the mount handles /mcp/...
app.mount("/mcp", mcp_server.mcp_app)  # both before the SPA catch-all

static_dir = Path(settings.static_dir)
if (static_dir / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith(("api/", "internal/", "media/", "mcp")):
        raise HTTPException(404)
    candidate = (static_dir / path).resolve()
    if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = static_dir / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return {"app": settings.app_name, "note": "frontend not built; run the Vite dev server"}
