import re
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user
from app.integrations import gateway
from app.models import User, WhatsAppLink, utcnow
from app.security import new_link_code

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


class LinkBody(BaseModel):
    phone: str


@router.post("/link")
async def start_link(body: LinkBody, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    digits = re.sub(r"\D", "", body.phone)
    if not 8 <= len(digits) <= 15:
        raise HTTPException(400, "Enter your WhatsApp number with country code, e.g. +92 300 1234567")
    bot = await gateway.bot_number()
    if not bot:
        raise HTTPException(503, "The WhatsApp bot is offline right now. Try again in a minute.")
    link = await session.scalar(select(WhatsAppLink).where(WhatsAppLink.user_id == user.id))
    if link is None:
        link = WhatsAppLink(user_id=user.id)
        session.add(link)
    link.phone = digits
    link.link_code = new_link_code()
    link.link_code_expires_at = utcnow() + timedelta(minutes=30)
    await session.commit()
    return {
        "code": link.link_code,
        "bot_number": bot,
        "wa_link": f"https://wa.me/{bot}?text={quote(link.link_code)}",
        "expires_at": link.link_code_expires_at.isoformat(),
    }


@router.get("/status")
async def link_status(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    link = await session.scalar(select(WhatsAppLink).where(WhatsAppLink.user_id == user.id))
    if link is None:
        return {"linked": False}
    return {
        "linked": bool(link.verified_at),
        "phone": link.phone,
        "verified_at": link.verified_at.isoformat() if link.verified_at else None,
        "pending_code": link.link_code,
    }


@router.delete("")
async def unlink(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    link = await session.scalar(select(WhatsAppLink).where(WhatsAppLink.user_id == user.id))
    if link:
        await session.delete(link)
        await session.commit()
    return {"ok": True}
