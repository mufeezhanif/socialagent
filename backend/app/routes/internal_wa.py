"""Called only by the local Baileys gateway (shared secret, 127.0.0.1)."""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import WhatsAppLink
from app.security import internal_secret_ok
from app.worker.queue import enqueue

router = APIRouter(prefix="/internal/wa", tags=["internal"])


def require_secret(x_internal_secret: str | None = Header(default=None)) -> None:
    if not internal_secret_ok(x_internal_secret):
        raise HTTPException(403, "forbidden")


class WaEvent(BaseModel):
    id: str
    jid: str
    jid_alt: str | None = None
    kind: str = "text"
    text: str = ""
    media_path: str | None = None
    reaction: str | None = None
    too_large: bool = False


class WaEvents(BaseModel):
    events: list[WaEvent]


@router.post("/events", dependencies=[Depends(require_secret)])
async def events(body: WaEvents, session: AsyncSession = Depends(get_session)):
    queued = 0
    for ev in body.events:
        payload = {
            "channel": "whatsapp",
            "chat_ref": ev.jid,
            "jid_alt": ev.jid_alt,
            "kind": ev.kind,
            "text": ev.text,
            "media_path": ev.media_path,
            "reaction": ev.reaction,
            "provider_message_id": ev.id,
            "too_large": ev.too_large,
        }
        if await enqueue(session, "inbound", payload=payload, dedupe_key=f"in:{ev.id}"):
            queued += 1
    await session.commit()
    return {"queued": queued}


@router.get("/allowlist", dependencies=[Depends(require_secret)])
async def allowlist(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(WhatsAppLink.jid, WhatsAppLink.jid_alt).where(WhatsAppLink.verified_at.is_not(None)))).all()
    jids = sorted({j for row in rows for j in row if j})
    return {"jids": jids}
