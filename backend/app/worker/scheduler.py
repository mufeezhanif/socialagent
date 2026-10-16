import asyncio
import logging

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Draft, DraftStatus as S, utcnow
from app.worker.queue import enqueue

log = logging.getLogger(__name__)


async def tick() -> int:
    async with SessionLocal() as session:
        due = (
            await session.scalars(
                select(Draft).where(Draft.status == S.SCHEDULED, Draft.publish_at <= utcnow()).limit(20)
            )
        ).all()
        for draft in due:
            draft.status = S.PUBLISHING
            await enqueue(
                session,
                "publish",
                draft_id=draft.id,
                dedupe_key=f"publish:{draft.id}:{int(draft.publish_at.timestamp())}",
            )
        await session.commit()
        return len(due)


async def loop(interval_s: float = 15) -> None:
    while True:
        try:
            count = await tick()
            if count:
                log.info("scheduler queued %d post(s)", count)
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval_s)
