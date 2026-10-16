"""Postgres/SQLite-backed job queue. Claiming is an atomic conditional UPDATE, so it is safe on both."""

import asyncio
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Job, utcnow

_wake = asyncio.Event()


def wake() -> None:
    _wake.set()


async def wait_for_work(timeout: float) -> None:
    try:
        await asyncio.wait_for(_wake.wait(), timeout)
    except TimeoutError:
        pass
    _wake.clear()


async def enqueue(
    session: AsyncSession,
    kind: str,
    *,
    draft_id: str | None = None,
    payload: dict | None = None,
    dedupe_key: str | None = None,
    run_after: datetime | None = None,
    max_attempts: int = 1,
) -> Job | None:
    """Adds a job inside the caller's transaction. Returns None if a job with the same dedupe_key exists."""
    if dedupe_key and await session.scalar(select(Job.id).where(Job.dedupe_key == dedupe_key)):
        return None
    job = Job(
        kind=kind,
        draft_id=draft_id,
        payload=payload or {},
        dedupe_key=dedupe_key,
        run_after=run_after or utcnow(),
        max_attempts=max_attempts,
    )
    session.add(job)
    await session.flush()
    wake()
    return job


async def claim(kinds: set[str], include: bool) -> Job | None:
    async with SessionLocal() as session:
        now = utcnow()
        query = select(Job.id).where(Job.status == "queued", Job.run_after <= now)
        query = query.where(Job.kind.in_(kinds)) if include else query.where(Job.kind.not_in(kinds))
        ids = (await session.scalars(query.order_by(Job.created_at).limit(5))).all()
        for job_id in ids:
            result = await session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "queued")
                .values(status="running", locked_at=now, attempts=Job.attempts + 1)
            )
            if result.rowcount == 1:
                await session.commit()
                return await session.get(Job, job_id)
        await session.commit()
    return None


async def finish(job_id: str, error: str | None = None) -> None:
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        if error is None:
            job.status = "done"
        elif job.attempts < job.max_attempts:
            backoff = min(300, 5 * 2 ** (job.attempts - 1)) * random.uniform(0.8, 1.3)
            job.status, job.run_after = "queued", utcnow() + timedelta(seconds=backoff)
            job.last_error = error[-2000:]
        else:
            job.status, job.last_error = "failed", error[-2000:]
        job.locked_at = None
        await session.commit()


async def recover_stuck(older_than_s: int = 900) -> None:
    """Jobs left 'running' by a crash or redeploy go back to the queue."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_s)
    async with SessionLocal() as session:
        await session.execute(
            update(Job).where(Job.status == "running", Job.locked_at < cutoff).values(status="queued", locked_at=None)
        )
        await session.commit()
