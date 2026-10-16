from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import copy, engine
from app.db import get_session
from app.deps import current_user
from app.models import AuditEvent, Draft, DraftStatus as S, User
from app.security import media_url

router = APIRouter(prefix="/api/drafts", tags=["drafts"])

CAPTION_STATES = {S.AWAITING_CAPTION_CHOICE, S.AWAITING_PUBLISH_CHOICE, S.AWAITING_SCHEDULE_TIME, S.SAVED}
PUBLISH_STATES = {S.AWAITING_PUBLISH_CHOICE, S.AWAITING_SCHEDULE_TIME, S.SAVED, S.SCHEDULED}


def _url(path: str | None) -> str | None:
    try:
        return media_url(path) if path else None
    except (ValueError, OSError):
        return None


def summary(d: Draft) -> dict:
    return {
        "id": d.id,
        "status": d.status,
        "status_label": copy.STATUS_LABELS.get(d.status, d.status),
        "channel": d.channel,
        "style": d.style,
        "revision": d.revision,
        "duration_in": d.duration_in,
        "duration_out": d.duration_out,
        "cover_url": _url(d.cover_path),
        "caption_final": d.caption_final,
        "publish_at": d.publish_at.isoformat() if d.publish_at else None,
        "ig_permalink": d.ig_permalink,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


async def detail(session: AsyncSession, d: Draft) -> dict:
    events = (
        await session.scalars(select(AuditEvent).where(AuditEvent.draft_id == d.id).order_by(AuditEvent.created_at))
    ).all()
    sb = d.storyboard or {}
    return {
        **summary(d),
        "source_url": _url(d.source_path),
        "master_url": _url(d.master_path),
        "preview_url": _url(d.preview_path),
        "edit_summary": d.edit_summary or [],
        "storyboard": {k: sb.get(k) for k in ("hook_text", "punchline_text", "cta_text", "scene_description",
                                              "question_for_user", "edit_notes", "style", "music")},
        "transcript": (d.transcript or {}).get("text", ""),
        "user_context": d.user_context,
        "revision_notes": d.revision_notes or [],
        "caption_pack": d.caption_pack,
        "hashtags_final": d.hashtags_final or [],
        "error": d.error,
        "failed_stage": d.failed_stage,
        "gates": {
            "video_approved": d.video_approved_rev is not None and d.video_approved_rev == d.revision,
            "caption_approved": bool(d.caption_approved_at),
            "publish_confirmed": bool(d.publish_confirmed_at),
        },
        "events": [
            {"actor": e.actor, "action": e.action, "detail": e.detail, "at": e.created_at.isoformat()} for e in events
        ],
    }


async def _owned(session: AsyncSession, user: User, draft_id: str) -> Draft:
    draft = await session.get(Draft, draft_id)
    if draft is None or draft.user_id != user.id:
        raise HTTPException(404, "Draft not found")
    return draft


async def _act(user: User, draft_id: str, allowed: set[str] | None, fn, *args) -> dict:
    async def action(ctx, draft):
        if allowed is not None and draft.status not in allowed:
            raise HTTPException(409, f"Not possible while the draft is {copy.STATUS_LABELS.get(draft.status, draft.status)}")
        await fn(ctx, draft, *args)

    try:
        await engine.run_action(user.id, draft_id, action)
    except LookupError:
        raise HTTPException(404, "Draft not found")
    from app.db import SessionLocal

    async with SessionLocal() as session:
        return await detail(session, await session.get(Draft, draft_id))


@router.get("")
async def list_drafts(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    drafts = (
        await session.scalars(
            select(Draft).where(Draft.user_id == user.id, Draft.status != S.DISCARDED).order_by(Draft.created_at.desc())
        )
    ).all()
    return [summary(d) for d in drafts]


@router.get("/{draft_id}")
async def get_draft(draft_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await detail(session, await _owned(session, user, draft_id))


class NotesBody(BaseModel):
    notes: str


class StyleBody(BaseModel):
    style: str | None = None


class CaptionBody(BaseModel):
    option: int | None = None
    text: str | None = None
    hashtags: list[str] | None = None


class TweakBody(BaseModel):
    tweak: str | None = None


class PublishBody(BaseModel):
    mode: str  # now | schedule
    publish_at: datetime | None = None


@router.post("/{draft_id}/approve")
async def approve(draft_id: str, user: User = Depends(current_user)):
    return await _act(user, draft_id, {S.AWAITING_VIDEO_APPROVAL, S.AWAITING_CHANGE_NOTES}, engine.approve_video)


@router.post("/{draft_id}/changes")
async def changes(draft_id: str, body: NotesBody, user: User = Depends(current_user)):
    return await _act(user, draft_id, {S.AWAITING_VIDEO_APPROVAL, S.AWAITING_CHANGE_NOTES}, engine.request_changes, body.notes)


@router.post("/{draft_id}/style")
async def style(draft_id: str, body: StyleBody, user: User = Depends(current_user)):
    return await _act(user, draft_id, {S.AWAITING_VIDEO_APPROVAL, S.AWAITING_CHANGE_NOTES}, engine.try_style, body.style)


@router.post("/{draft_id}/motion")
async def motion(draft_id: str, user: User = Depends(current_user)):
    return await _act(user, draft_id, {S.AWAITING_VIDEO_APPROVAL, S.AWAITING_CHANGE_NOTES}, engine.try_motion)


@router.post("/{draft_id}/discard")
async def discard(draft_id: str, user: User = Depends(current_user)):
    return await _act(user, draft_id, None, engine.discard)


@router.post("/{draft_id}/caption")
async def caption(draft_id: str, body: CaptionBody, user: User = Depends(current_user)):
    if body.option:
        return await _act(user, draft_id, CAPTION_STATES, engine.choose_caption, body.option)
    if body.text and body.text.strip():
        return await _act(user, draft_id, CAPTION_STATES, engine.set_own_caption, body.text, body.hashtags)
    raise HTTPException(400, "Pick an option or write a caption")


@router.post("/{draft_id}/captions/regenerate")
async def regenerate(draft_id: str, body: TweakBody, user: User = Depends(current_user)):
    return await _act(user, draft_id, CAPTION_STATES | {S.AWAITING_CONTEXT}, engine.start_captions, body.tweak)


@router.post("/{draft_id}/publish")
async def publish(draft_id: str, body: PublishBody, user: User = Depends(current_user)):
    if body.mode == "now":
        return await _act(user, draft_id, PUBLISH_STATES, engine.publish_now)
    if body.mode == "schedule" and body.publish_at:
        when = body.publish_at if body.publish_at.tzinfo else body.publish_at.replace(tzinfo=engine.user_tz(user))
        return await _act(user, draft_id, PUBLISH_STATES, engine.schedule_at, when)
    raise HTTPException(400, "mode must be 'now' or 'schedule' with publish_at")


@router.post("/{draft_id}/unschedule")
async def unschedule(draft_id: str, user: User = Depends(current_user)):
    return await _act(user, draft_id, {S.SCHEDULED}, engine.unschedule)


@router.post("/{draft_id}/save")
async def save(draft_id: str, user: User = Depends(current_user)):
    return await _act(user, draft_id, None, engine.save_draft)


@router.post("/{draft_id}/retry")
async def retry(draft_id: str, user: User = Depends(current_user)):
    return await _act(user, draft_id, {S.FAILED}, engine.retry)
