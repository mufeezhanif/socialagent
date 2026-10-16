"""Web chat: the same agent as WhatsApp, in the browser (judge access + demo fallback)."""

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.deps import current_user
from app.models import Message, User
from app.security import media_url
from app.worker.queue import enqueue

router = APIRouter(prefix="/api/chat", tags=["chat"])
VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".webm", ".3gp", ".mkv"}


class ChatBody(BaseModel):
    text: str


def _event(user: User, **kwargs) -> dict:
    return {"channel": "web", "chat_ref": f"web:{user.id}", "user_id": user.id,
            "provider_message_id": f"web-{secrets.token_hex(8)}", **kwargs}


@router.get("/messages")
async def messages(after: str | None = None, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    query = select(Message).where(Message.user_id == user.id).order_by(Message.created_at.desc()).limit(80)
    rows = list(reversed((await session.scalars(query)).all()))
    if after:
        ids = [m.id for m in rows]
        rows = rows[ids.index(after) + 1 :] if after in ids else rows
    out = []
    for m in rows:
        body = m.body or {}
        video = body.get("video") or (body.get("media") if m.kind == "video" else None)
        url = None
        if video:
            try:
                url = media_url(video)
            except (ValueError, OSError):
                url = None
        out.append({
            "id": m.id,
            "direction": m.direction,
            "channel": m.channel,
            "kind": m.kind,
            "text": body.get("text") or (body.get("reaction") or ""),
            "video_url": url,
            "draft_id": m.draft_id,
            "at": m.created_at.isoformat(),
        })
    return out


@router.post("/messages")
async def send_message(body: ChatBody, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Empty message")
    await enqueue(session, "inbound", payload=_event(user, kind="text", text=text[:4000]))
    await session.commit()
    return {"ok": True}


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    caption: str = Form(""),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    suffix = Path(file.filename or "video.mp4").suffix.lower()
    if suffix not in VIDEO_TYPES:
        raise HTTPException(400, "Upload a video file (mp4, mov, webm)")
    inbox = Path(settings.media_dir) / "in"
    inbox.mkdir(parents=True, exist_ok=True)
    dest = inbox / f"web_{secrets.token_hex(8)}{suffix}"
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"Video is larger than {settings.max_upload_mb} MB")
            out.write(chunk)
    await enqueue(session, "inbound", payload=_event(user, kind="video", text=caption.strip()[:2000], media_path=str(dest)))
    await session.commit()
    return {"ok": True}
