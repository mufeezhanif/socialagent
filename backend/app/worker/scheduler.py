import asyncio
import logging

from sqlalchemy import select, update

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
        queued = 0
        for draft in due:
            # conditional: a concurrent "post now" / unschedule may have moved it since the select
            claimed = await session.execute(
                update(Draft).where(Draft.id == draft.id, Draft.status == S.SCHEDULED).values(status=S.PUBLISHING)
            )
            if claimed.rowcount != 1:
                continue
            queued += 1
            await enqueue(
                session,
                "publish",
                draft_id=draft.id,
                dedupe_key=f"publish:{draft.id}:{int(draft.publish_at.timestamp())}",
            )
        await session.commit()
        return queued


async def refresh_instagram_tokens() -> None:
    """Long-lived Instagram tokens last ~60 days; refresh those expiring within 10 days (allowed after 24 h)."""
    from datetime import timedelta

    from app.integrations import instagram_api
    from app.models import InstagramAccount
    from app.security import decrypt_text, encrypt_text

    now = utcnow()
    async with SessionLocal() as session:
        accounts = (
            await session.scalars(
                select(InstagramAccount).where(
                    InstagramAccount.token_expires_at < now + timedelta(days=10),
                    InstagramAccount.connected_at < now - timedelta(hours=24),
                )
            )
        ).all()
        for account in accounts:
            token = decrypt_text(account.access_token_enc)
            if not token:
                continue
            try:
                new_token, expires = await instagram_api.refresh(token)
            except instagram_api.InstagramError as exc:
                log.warning("token refresh failed for @%s: %s", account.username, exc)
                account.status = "expired" if account.token_expires_at < now else account.status
                continue
            account.access_token_enc, account.token_expires_at, account.status = encrypt_text(new_token), expires, "ok"
        await session.commit()


async def loop(interval_s: float = 15) -> None:
    ticks = 0
    while True:
        try:
            count = await tick()
            if count:
                log.info("scheduler queued %d post(s)", count)
            if ticks % 240 == 0:  # about hourly
                await refresh_instagram_tokens()
        except Exception:
            log.exception("scheduler tick failed")
        ticks += 1
        await asyncio.sleep(interval_s)
