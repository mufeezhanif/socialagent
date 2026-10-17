import re
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.engine import get_brand
from app.db import get_session
from app.deps import current_user
from app.models import TasteMemory, User, utcnow
from app.pipeline.styles import STYLE_ORDER
from app.services.captions import clean_tag
from app.services.taste import MAX_LINE, MAX_NOTES

router = APIRouter(prefix="/api/brand", tags=["brand"])
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class BrandBody(BaseModel):
    niche: str = ""
    tone: str = ""
    audience: str = ""
    emoji_level: Literal["none", "some", "lots"] = "some"
    cta: str = ""
    default_hashtags: list[str] = []
    banned_words: list[str] = []
    primary_color: str = "#FFFFFF"
    accent_color: str = "#FFD400"
    default_style: str = "clean"
    preferred_post_time: str = "19:00"
    timezone: str = "Asia/Karachi"


def _payload(brand, user: User) -> dict:
    return {
        "niche": brand.niche,
        "tone": brand.tone,
        "audience": brand.audience,
        "emoji_level": brand.emoji_level,
        "cta": brand.cta,
        "default_hashtags": brand.default_hashtags or [],
        "banned_words": brand.banned_words or [],
        "primary_color": brand.primary_color,
        "accent_color": brand.accent_color,
        "default_style": brand.default_style,
        "preferred_post_time": brand.preferred_post_time,
        "timezone": user.timezone,
        "styles": STYLE_ORDER,
    }


@router.get("")
async def read_brand(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    brand = await get_brand(session, user.id)
    await session.commit()
    return _payload(brand, user)


@router.put("")
async def update_brand(body: BrandBody, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if not (HEX_RE.match(body.primary_color) and HEX_RE.match(body.accent_color)):
        raise HTTPException(400, "Colours must look like #RRGGBB")
    if body.default_style not in STYLE_ORDER:
        raise HTTPException(400, "Unknown style")
    if not TIME_RE.match(body.preferred_post_time):
        raise HTTPException(400, "Time must look like 19:00")
    try:
        ZoneInfo(body.timezone)
    except Exception:
        raise HTTPException(400, "Unknown timezone")
    brand = await get_brand(session, user.id)
    brand.niche, brand.tone, brand.audience = body.niche[:200], body.tone[:200], body.audience[:200]
    brand.emoji_level, brand.cta = body.emoji_level, body.cta[:200]
    brand.default_hashtags = [t for t in (clean_tag(h) for h in body.default_hashtags) if t][:10]
    brand.banned_words = [w.strip()[:40] for w in body.banned_words if w.strip()][:30]
    brand.primary_color, brand.accent_color = body.primary_color.upper(), body.accent_color.upper()
    brand.default_style, brand.preferred_post_time = body.default_style, body.preferred_post_time
    db_user = await session.get(User, user.id)
    db_user.timezone = body.timezone
    await session.commit()
    return _payload(brand, db_user)


class TasteBody(BaseModel):
    notes: list[str]


async def _taste_payload(session: AsyncSession, user_id: str) -> dict:
    memory = await session.get(TasteMemory, user_id)
    return {
        "notes": list(memory.notes or []) if memory else [],
        "updated_at": memory.updated_at.isoformat() if memory else None,
        "signals_seen": memory.signals_seen if memory else 0,
    }


@router.get("/taste")
async def read_taste(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await _taste_payload(session, user.id)


@router.put("/taste")
async def update_taste(body: TasteBody, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    notes = [n.strip() for n in body.notes]
    if any(not n for n in notes):
        raise HTTPException(400, "Preferences can't be empty")
    if len(notes) > MAX_NOTES:
        raise HTTPException(400, f"Keep it to {MAX_NOTES} preferences")
    if any(len(n) > MAX_LINE for n in notes):
        raise HTTPException(400, f"Each preference must be {MAX_LINE} characters or fewer")
    memory = await session.get(TasteMemory, user.id)
    if memory is None:
        memory = TasteMemory(user_id=user.id)
        session.add(memory)
    memory.notes, memory.updated_at = notes, utcnow()
    await session.commit()
    return await _taste_payload(session, user.id)


@router.delete("/taste")
async def clear_taste(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    memory = await session.get(TasteMemory, user.id)
    if memory is not None:
        memory.notes, memory.updated_at = [], utcnow()
        await session.commit()
    return await _taste_payload(session, user.id)
