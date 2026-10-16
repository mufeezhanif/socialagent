from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import admin_user
from app.integrations import gateway
from app.models import Draft, Job, User

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_user)])


class PairBody(BaseModel):
    phone: str


class PauseBody(BaseModel):
    paused: bool


@router.get("/wa/status")
async def wa_status():
    try:
        return await gateway.status()
    except gateway.GatewayError as exc:
        return {"status": "offline", "error": str(exc)}


@router.post("/wa/pair-code")
async def wa_pair_code(body: PairBody):
    digits = "".join(ch for ch in body.phone if ch.isdigit())
    if not 8 <= len(digits) <= 15:
        raise HTTPException(400, "Phone number with country code, digits only")
    try:
        return await gateway.pair_code(digits)
    except gateway.GatewayError as exc:
        raise HTTPException(502, str(exc))


@router.post("/wa/logout")
async def wa_logout():
    try:
        return await gateway.logout()
    except gateway.GatewayError as exc:
        raise HTTPException(502, str(exc))


@router.post("/wa/pause")
async def wa_pause(body: PauseBody):
    try:
        return await gateway.set_paused(body.paused)
    except gateway.GatewayError as exc:
        raise HTTPException(502, str(exc))


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)):
    users = await session.scalar(select(func.count(User.id)))
    drafts = dict((await session.execute(select(Draft.status, func.count()).group_by(Draft.status))).all())
    jobs = dict((await session.execute(select(Job.status, func.count()).group_by(Job.status))).all())
    return {"users": users, "drafts": drafts, "jobs": jobs}
