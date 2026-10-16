import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels import get_channel
from app.models import Message, utcnow

log = logging.getLogger(__name__)
_last_ts: datetime | None = None


def next_timestamp() -> datetime:
    """Strictly increasing timestamps so chat order is stable even with a coarse system clock."""
    global _last_ts
    now = utcnow()
    if _last_ts is not None and now <= _last_ts:
        now = _last_ts + timedelta(microseconds=1)
    _last_ts = now
    return now


async def send(
    session: AsyncSession,
    *,
    user_id: str,
    channel: str,
    chat_ref: str,
    text: str = "",
    video: Path | str | None = None,
    draft_id: str | None = None,
) -> None:
    """Deliver through the channel and record it. Delivery failures are logged, never raised."""
    provider_id = None
    transport = get_channel(channel)
    try:
        if video:
            provider_id = await transport.send_video(chat_ref, Path(video), text)
        else:
            provider_id = await transport.send_text(chat_ref, text)
    except Exception as exc:
        log.warning("send via %s to %s failed: %s", channel, chat_ref, exc)
    session.add(
        Message(
            user_id=user_id,
            draft_id=draft_id,
            channel=channel,
            direction="out",
            provider_message_id=provider_id,
            kind="video" if video else "text",
            body={"text": text, "video": str(video) if video else None},
            created_at=next_timestamp(),
        )
    )


async def typing(channel: str, chat_ref: str) -> None:
    try:
        await get_channel(channel).typing(chat_ref)
    except Exception:
        pass
