import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.pipeline.transcribe import warm_up
from app.routes import admin, auth, brand, chat, drafts, health, instagram, internal_wa, media, whatsapp_link
from app.worker import scheduler
from app.worker.runner import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
    await init_db()
    worker = Worker()
    tasks = [asyncio.create_task(worker.run()), asyncio.create_task(scheduler.loop())]
    asyncio.get_running_loop().run_in_executor(None, warm_up)  # load Whisper before the first video
    log.info("%s started (env=%s, base=%s)", settings.app_name, settings.env, settings.app_base_url)
    yield
    worker.stop()
    for task in tasks:
        task.cancel()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
for router in (health.router, auth.router, whatsapp_link.router, instagram.router, brand.router, drafts.router,
               chat.router, media.router, admin.router, internal_wa.router):
    app.include_router(router)

static_dir = Path(settings.static_dir)
if (static_dir / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith(("api/", "internal/", "media/")):
        raise HTTPException(404)
    candidate = (static_dir / path).resolve()
    if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = static_dir / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return {"app": settings.app_name, "note": "frontend not built; run the Vite dev server"}
