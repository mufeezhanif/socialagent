import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.integrations import claude, gateway, instagram_api, llm

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(session: AsyncSession = Depends(get_session)):
    db_ok = True
    try:
        await session.execute(text("select 1"))
    except Exception:
        db_ok = False
    try:
        wa = (await gateway.status()).get("status", "unknown")
    except gateway.GatewayError:
        wa = "offline"
    return {
        "ok": db_ok,
        "db": db_ok,
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "whatsapp": wa,
        "claude": claude.enabled(),
        "llm_providers": llm.names(),
        "transcription": "groq" if settings.groq_api_key and settings.transcribe_provider != "local" else "local",
        "instagram": instagram_api.configured(),
        "render_engine": settings.render_engine,
    }
