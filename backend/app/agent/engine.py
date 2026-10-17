"""Conversation engine: one state machine per draft, shared by WhatsApp, web chat and dashboard buttons."""

import asyncio
import logging
import re
import shutil
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import copy, intents
from app.agent.timeparse import human_time, suggest_slot
from app.channels import get_channel
from app.config import settings
from app.db import SessionLocal
from app.integrations import gateway
from app.models import BrandProfile, Draft, DraftStatus as S, Message, User, WhatsAppLink, utcnow
from app.pipeline.render_hyperframes import hyperframes_available
from app.pipeline.styles import get_preset, next_style
from app.services import messaging, taste
from app.services.audit import audit
from app.services.publisher import instagram_account
from app.worker.queue import enqueue

log = logging.getLogger(__name__)
LINK_RE = re.compile(r"LINK-[A-Z0-9]{6}", re.IGNORECASE)
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


@dataclass
class InboundEvent:
    channel: str
    chat_ref: str
    kind: str = "text"  # text | video | audio | reaction | image | other
    text: str = ""
    provider_message_id: str | None = None
    media_path: str | None = None
    reaction: str | None = None
    user_id: str | None = None  # web channel only
    jid_alt: str | None = None
    too_large: bool = False


@dataclass
class Ctx:
    session: AsyncSession
    user: User
    channel: str
    chat_ref: str

    async def say(self, text: str, draft: Draft | None = None, video: Path | str | None = None) -> None:
        await messaging.send(
            self.session,
            user_id=self.user.id,
            channel=self.channel,
            chat_ref=self.chat_ref,
            text=text,
            video=video,
            draft_id=draft.id if draft else None,
        )


def dashboard_url(path: str = "/app") -> str:
    return f"{settings.frontend_url.rstrip('/')}{path}"


def draft_dir(user_id: str, draft_id: str) -> Path:
    return Path(settings.media_dir) / user_id / draft_id


def user_tz(user: User) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone or settings.default_timezone)
    except Exception:
        return ZoneInfo(settings.default_timezone)


async def get_brand(session: AsyncSession, user_id: str) -> BrandProfile:
    brand = await session.get(BrandProfile, user_id)
    if brand is None:
        brand = BrandProfile(user_id=user_id)
        session.add(brand)
        await session.flush()
    return brand


def brand_dict(brand: BrandProfile) -> dict:
    return {
        "niche": brand.niche,
        "tone": brand.tone,
        "audience": brand.audience,
        "emoji_level": brand.emoji_level,
        "cta": brand.cta,
        "default_hashtags": brand.default_hashtags or [],
        "banned_words": brand.banned_words or [],
        "accent_color": brand.accent_color,
        "default_style": brand.default_style,
    }


async def active_draft(ctx: Ctx) -> Draft | None:
    if not ctx.user.active_draft_id:
        return None
    return await ctx.session.get(Draft, ctx.user.active_draft_id)


# ---------------------------------------------------------------- inbound


async def resolve_user(session: AsyncSession, ev: InboundEvent) -> User | None:
    if ev.channel == "web":
        return await session.get(User, ev.user_id) if ev.user_id else None
    jids = [j for j in (ev.chat_ref, ev.jid_alt) if j]
    link = await session.scalar(
        select(WhatsAppLink).where(
            WhatsAppLink.verified_at.is_not(None), or_(WhatsAppLink.jid.in_(jids), WhatsAppLink.jid_alt.in_(jids))
        )
    )
    return await session.get(User, link.user_id) if link else None


async def try_link(session: AsyncSession, ev: InboundEvent) -> bool:
    match = LINK_RE.search(ev.text or "")
    if not match:
        return False
    link = await session.scalar(select(WhatsAppLink).where(WhatsAppLink.link_code == match.group(0).upper()))
    if link is None or (link.link_code_expires_at and link.link_code_expires_at < utcnow()):
        try:
            await get_channel(ev.channel).send_text(ev.chat_ref, copy.LINK_INVALID)
        except Exception as exc:
            log.warning("could not send link-invalid reply: %s", exc)
        return True
    jids = [j for j in (ev.chat_ref, ev.jid_alt) if j]
    others = await session.scalars(
        select(WhatsAppLink).where(
            WhatsAppLink.id != link.id, or_(WhatsAppLink.jid.in_(jids), WhatsAppLink.jid_alt.in_(jids))
        )
    )
    for other in others:  # one WhatsApp account belongs to one app account
        other.jid, other.jid_alt, other.verified_at = None, None, None
    await session.flush()
    link.jid, link.jid_alt, link.verified_at = ev.chat_ref, ev.jid_alt, utcnow()
    link.link_code, link.link_code_expires_at = None, None
    pn = next((j for j in jids if j.endswith("@s.whatsapp.net")), None)
    if pn:
        link.phone = pn.split("@", 1)[0].split(":", 1)[0]
    audit(session, link.user_id, None, "human", "whatsapp_linked")
    await session.commit()
    try:
        await gateway.allowlist_add(*jids)
    except Exception as exc:
        log.warning("allowlist update failed: %s", exc)
    await messaging.send(
        session,
        user_id=link.user_id,
        channel=ev.channel,
        chat_ref=ev.chat_ref,
        text=copy.WELCOME_LINKED.format(app=settings.app_name),
    )
    await session.commit()
    return True


async def handle_inbound(ev: InboundEvent) -> None:
    async with SessionLocal() as session:
        if ev.channel == "whatsapp" and ev.kind == "text" and LINK_RE.search(ev.text or ""):
            await try_link(session, ev)
            return
        user = await resolve_user(session, ev)
        if user is None:
            return  # not a linked user: ignore silently, store nothing
        user_id = user.id
        if ev.provider_message_id and await session.scalar(
            select(Message.id).where(Message.provider_message_id == ev.provider_message_id)
        ):
            return  # duplicate delivery
        session.add(
            Message(
                user_id=user_id,
                channel=ev.channel,
                direction="in",
                provider_message_id=ev.provider_message_id,
                kind=ev.kind,
                body={"text": ev.text, "media": ev.media_path, "reaction": ev.reaction},
                created_at=messaging.next_timestamp(),
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            return

    async with _locks[user_id]:
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            ctx = Ctx(session, user, ev.channel, ev.chat_ref)
            try:
                await dispatch(ctx, ev)
                await session.commit()
            except Exception:
                log.exception("dispatch failed for user %s", user_id)
                await session.rollback()
                ctx.user = await session.get(User, user_id)  # rollback expired it; lazy reload would raise MissingGreenlet
                await ctx.say(copy.FAILED.format(stage="reading your message"))
                await session.commit()


async def dispatch(ctx: Ctx, ev: InboundEvent) -> None:
    text = (ev.text or "").strip()
    if ev.kind == "audio":
        from app.pipeline.transcribe import transcribe

        heard = (await transcribe(ev.media_path)).get("text", "").strip() if ev.media_path else ""
        if not heard:
            await ctx.say("🎙️ I couldn't make out that voice note. Could you type it?")
            return
        text, ev.kind = heard, "text"
    low = text.lower().strip()

    if ev.kind == "text" and low in {"help", "menu"}:
        await ctx.say(copy.HELP.format(url=dashboard_url()))
        return
    if ev.kind == "text" and low == "status":
        await say_status(ctx)
        return
    if ev.kind == "video":
        if ev.too_large or not ev.media_path:
            await ctx.say(copy.TOO_BIG.format(max=settings.max_video_seconds))
            return
        await start_draft(ctx, Path(ev.media_path), text or None)
        return
    if ev.kind in {"image", "other"}:
        await ctx.say(copy.ONLY_VIDEO)
        return

    draft = await active_draft(ctx)
    if draft is None or draft.status in S.TERMINAL:
        if ev.kind == "text":
            await ctx.say(copy.NO_DRAFT)
        return
    if ev.kind == "reaction":
        if draft.status == S.AWAITING_VIDEO_APPROVAL and intents.is_like(ev.reaction):
            await approve_video(ctx, draft)
        return
    if low == "retry":
        if draft.status == S.FAILED:
            await retry(ctx, draft)
        else:
            await say_status(ctx)
        return

    st = draft.status
    if st in S.WORKING:
        await ctx.say(copy.STILL_WORKING, draft)
    elif st == S.AWAITING_VIDEO_APPROVAL:
        intent = await intents.approval(text)
        if intent.name == "approve":
            await approve_video(ctx, draft)
        elif intent.name == "change":
            await request_changes(ctx, draft, intent.data.get("notes", ""))
        elif intent.name == "style":
            await try_style(ctx, draft, intent.data.get("style") or None)
        elif intent.name == "discard":
            await discard(ctx, draft)
        elif intent.name == "motion":
            await try_motion(ctx, draft)
        else:
            await ctx.say(copy.UNCLEAR + copy.approval_options(hyperframes_available()), draft)
    elif st == S.AWAITING_CHANGE_NOTES:
        if low in {"cancel", "back", "nothing", "never mind", "nevermind"}:
            draft.status = S.AWAITING_VIDEO_APPROVAL
            await ctx.say("OK, no changes." + copy.approval_options(hyperframes_available()), draft)
        else:
            await request_changes(ctx, draft, text)
    elif st == S.AWAITING_CONTEXT:
        intent = intents.context(text)
        if intent.name == "context":
            draft.user_context = f"{draft.user_context}\n{intent.data['text']}" if draft.user_context else intent.data["text"]
        await start_captions(ctx, draft)
    elif st == S.AWAITING_CAPTION_CHOICE:
        intent = await intents.caption(text)
        option = int(intent.data.get("option") or 0)
        if intent.name == "choose" and 1 <= option <= 3:
            await choose_caption(ctx, draft, option)
        elif intent.name == "own_caption" and intent.data.get("text"):
            await set_own_caption(ctx, draft, intent.data["text"])
        elif intent.name == "tweak":
            await start_captions(ctx, draft, tweak=intent.data.get("text") or text)
        else:
            await ctx.say(copy.UNCLEAR + copy.CAPTION_REPLY, draft)
    elif st == S.AWAITING_PUBLISH_CHOICE:
        intent = intents.publish_choice(text)
        if intent.name == "now":
            await publish_now(ctx, draft)
        elif intent.name == "schedule":
            if intent.data.get("when"):
                await schedule_from_text(ctx, draft, intent.data["when"])
            else:
                await ask_time(ctx, draft)
        elif intent.name == "save":
            await save_draft(ctx, draft)
        else:
            await ctx.say(copy.UNCLEAR + "\n\n" + copy.ASK_PUBLISH, draft)
    elif st == S.AWAITING_SCHEDULE_TIME:
        if low in {"cancel", "back"}:
            draft.status = S.AWAITING_PUBLISH_CHOICE
            await ctx.say(copy.ASK_PUBLISH, draft)
        elif low in {"now", "post now"}:
            await publish_now(ctx, draft)
        else:
            await schedule_from_text(ctx, draft, text)
    elif st == S.SCHEDULED:
        if low in {"cancel", "unschedule", "stop"}:
            await unschedule(ctx, draft)
        elif low in {"now", "post now", "1"}:
            await publish_now(ctx, draft)
        else:
            await say_status(ctx)
    elif st == S.FAILED:
        await ctx.say(copy.FAILED.format(stage=draft.failed_stage or "working on your video"), draft)


# ---------------------------------------------------------------- actions (also used by the dashboard)


DAILY_VIDEO_LIMIT = 25


async def start_draft(ctx: Ctx, src: Path, user_context: str | None) -> Draft | None:
    since = utcnow() - timedelta(hours=24)
    recent = await ctx.session.scalar(
        select(func.count(Draft.id)).where(Draft.user_id == ctx.user.id, Draft.created_at >= since)
    )
    if recent >= DAILY_VIDEO_LIMIT:
        await ctx.say(f"You've hit today's limit of {DAILY_VIDEO_LIMIT} videos. Try again tomorrow.")
        return None
    previous = await active_draft(ctx)
    replaced = previous is not None and previous.status not in S.TERMINAL
    if replaced:
        previous.status = S.SAVED
    brand = await get_brand(ctx.session, ctx.user.id)
    draft = Draft(
        user_id=ctx.user.id,
        channel=ctx.channel,
        chat_ref=ctx.chat_ref,
        status=S.PROCESSING,
        style=brand.default_style,
        user_context=user_context,
        revision_notes=[],
    )
    ctx.session.add(draft)
    await ctx.session.flush()
    folder = draft_dir(ctx.user.id, draft.id)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"source{src.suffix.lower() or '.mp4'}"
    await asyncio.to_thread(shutil.move, str(src), str(dest))
    draft.source_path = str(dest)
    ctx.user.active_draft_id = draft.id
    audit(ctx.session, ctx.user.id, draft.id, "human", "sent_video", channel=ctx.channel, context=user_context)
    await enqueue(ctx.session, "process_video", draft_id=draft.id, dedupe_key=f"process:{draft.id}")
    await ctx.say(copy.RECEIVED_REPLACED if replaced else copy.RECEIVED, draft)
    return draft


async def approve_video(ctx: Ctx, draft: Draft) -> None:
    draft.video_approved_rev = draft.revision
    audit(ctx.session, ctx.user.id, draft.id, "human", "approved_edit", revision=draft.revision)
    await taste.queue_learning(ctx.session, ctx.user.id, draft.id)
    if draft.user_context:
        await start_captions(ctx, draft, prefix="Approved ✅\n\n")
    else:
        draft.status = S.AWAITING_CONTEXT
        await ctx.say(copy.ASK_CONTEXT, draft)


async def request_changes(ctx: Ctx, draft: Draft, notes: str) -> None:
    notes = (notes or "").strip()
    if not notes:
        draft.status = S.AWAITING_CHANGE_NOTES
        await ctx.say(copy.ASK_CHANGES, draft)
        return
    done = len(draft.revision_notes or [])
    if done >= settings.max_revisions:
        draft.status = S.AWAITING_VIDEO_APPROVAL
        await ctx.say(copy.REVISION_LIMIT.format(max=settings.max_revisions, url=dashboard_url(f"/app/drafts/{draft.id}")), draft)
        return
    draft.revision_notes = [*(draft.revision_notes or []), notes]
    draft.status = S.REVISING
    audit(ctx.session, ctx.user.id, draft.id, "human", "requested_changes", notes=notes)
    await taste.queue_learning(ctx.session, ctx.user.id, draft.id)
    await enqueue(ctx.session, "revise_video", draft_id=draft.id, payload={}, dedupe_key=f"revise:{draft.id}:n{done + 1}")
    await ctx.say(copy.REVISING.format(n=done + 1, max=settings.max_revisions), draft)


async def try_style(ctx: Ctx, draft: Draft, style: str | None) -> None:
    tried = list((draft.probe or {}).get("styles_tried") or [draft.style])
    new_style = style or next_style(draft.style, tried)
    draft.status = S.REVISING
    audit(ctx.session, ctx.user.id, draft.id, "human", "requested_style", style=new_style)
    await enqueue(
        ctx.session,
        "revise_video",
        draft_id=draft.id,
        payload={"style": new_style},
        dedupe_key=f"style:{draft.id}:{new_style}:r{draft.revision}",
    )
    await ctx.say(copy.NEW_STYLE.format(style=get_preset(new_style).label), draft)


async def try_motion(ctx: Ctx, draft: Draft) -> None:
    if not hyperframes_available():
        draft.status = S.AWAITING_VIDEO_APPROVAL
        await ctx.say(copy.MOTION_UNAVAILABLE + copy.approval_options(False), draft)
        return
    draft.status = S.REVISING
    audit(ctx.session, ctx.user.id, draft.id, "human", "requested_motion")
    await enqueue(
        ctx.session, "revise_video", draft_id=draft.id, payload={"motion": True},
        dedupe_key=f"motion:{draft.id}:r{draft.revision}",
    )
    await ctx.say(copy.MOTION_START, draft)


async def discard(ctx: Ctx, draft: Draft) -> None:
    draft.status = S.DISCARDED
    if ctx.user.active_draft_id == draft.id:
        ctx.user.active_draft_id = None
    audit(ctx.session, ctx.user.id, draft.id, "human", "discarded")
    await taste.queue_learning(ctx.session, ctx.user.id, draft.id)
    await ctx.say(copy.DISCARDED, draft)


async def start_captions(ctx: Ctx, draft: Draft, tweak: str | None = None, prefix: str = "") -> None:
    draft.status = S.CAPTIONING
    await enqueue(ctx.session, "caption_pack", draft_id=draft.id, payload={"tweak": tweak})
    await ctx.say(prefix + copy.WRITING_CAPTIONS, draft)


async def choose_caption(ctx: Ctx, draft: Draft, option: int) -> None:
    pack = draft.caption_pack or {}
    options = pack.get("options") or []
    if not 1 <= option <= len(options):
        await ctx.say(copy.UNCLEAR + copy.CAPTION_REPLY, draft)
        return
    draft.caption_final = options[option - 1]["text"]
    draft.hashtags_final = pack.get("hashtags") or []
    draft.caption_approved_at = utcnow()
    audit(ctx.session, ctx.user.id, draft.id, "human", "chose_caption", option=option)
    await taste.queue_learning(ctx.session, ctx.user.id, draft.id)
    await ask_publish(ctx, draft, prefix=copy.CAPTION_SET + "\n\n")


async def set_own_caption(ctx: Ctx, draft: Draft, text: str, hashtags: list[str] | None = None) -> None:
    draft.caption_final = text.strip()[:2000]
    draft.hashtags_final = hashtags if hashtags is not None else (draft.caption_pack or {}).get("hashtags") or []
    draft.caption_approved_at = utcnow()
    audit(ctx.session, ctx.user.id, draft.id, "human", "wrote_caption")
    await taste.queue_learning(ctx.session, ctx.user.id, draft.id)
    await ask_publish(ctx, draft, prefix=copy.CAPTION_SET + "\n\n")


async def _instagram_ready(ctx: Ctx) -> bool:
    return settings.publish_dry_run or await instagram_account(ctx.session, ctx.user.id) is not None


async def ask_publish(ctx: Ctx, draft: Draft, prefix: str = "") -> None:
    draft.status = S.AWAITING_PUBLISH_CHOICE
    ask = copy.ASK_PUBLISH if await _instagram_ready(ctx) else copy.NEED_INSTAGRAM.format(url=dashboard_url("/onboarding"))
    await ctx.say(prefix + ask, draft)


async def publish_now(ctx: Ctx, draft: Draft) -> None:
    if not await _instagram_ready(ctx):
        draft.status = S.AWAITING_PUBLISH_CHOICE
        await ctx.say(copy.NEED_INSTAGRAM.format(url=dashboard_url("/onboarding")), draft)
        return
    now = utcnow()
    draft.publish_confirmed_at, draft.publish_mode, draft.publish_at = now, "now", now
    draft.status = S.PUBLISHING
    audit(ctx.session, ctx.user.id, draft.id, "human", "confirmed_post_now")
    await enqueue(ctx.session, "publish", draft_id=draft.id, dedupe_key=f"publish:{draft.id}:{int(now.timestamp())}")
    await ctx.say(copy.PUBLISHING, draft)


async def ask_time(ctx: Ctx, draft: Draft) -> None:
    brand = await get_brand(ctx.session, ctx.user.id)
    slot = suggest_slot(datetime.now(user_tz(ctx.user)), brand.preferred_post_time)
    draft.status = S.AWAITING_SCHEDULE_TIME
    await ctx.say(copy.ASK_TIME.format(suggestion=human_time(slot)), draft)


async def schedule_from_text(ctx: Ctx, draft: Draft, text: str) -> None:
    when = await intents.schedule_time(text, datetime.now(user_tz(ctx.user)))
    if when is None:
        draft.status = S.AWAITING_SCHEDULE_TIME
        await ctx.say(copy.TIME_UNCLEAR, draft)
        return
    await schedule_at(ctx, draft, when)


async def schedule_at(ctx: Ctx, draft: Draft, when: datetime) -> None:
    now = datetime.now(timezone.utc)
    if when <= now + timedelta(seconds=20):
        draft.status = S.AWAITING_SCHEDULE_TIME
        await ctx.say(copy.TIME_PAST, draft)
        return
    if when > now + timedelta(days=60):
        draft.status = S.AWAITING_SCHEDULE_TIME
        await ctx.say("Pick a time within the next 60 days.", draft)
        return
    if not await _instagram_ready(ctx):
        draft.status = S.AWAITING_PUBLISH_CHOICE
        await ctx.say(copy.NEED_INSTAGRAM.format(url=dashboard_url("/onboarding")), draft)
        return
    draft.publish_at = when.astimezone(timezone.utc)
    draft.publish_mode, draft.publish_confirmed_at, draft.status = "scheduled", utcnow(), S.SCHEDULED
    audit(ctx.session, ctx.user.id, draft.id, "human", "scheduled", at=draft.publish_at.isoformat())
    await ctx.say(copy.SCHEDULED.format(when=human_time(when.astimezone(user_tz(ctx.user)))), draft)


async def unschedule(ctx: Ctx, draft: Draft) -> None:
    draft.status, draft.publish_at, draft.publish_confirmed_at = S.AWAITING_PUBLISH_CHOICE, None, None
    audit(ctx.session, ctx.user.id, draft.id, "human", "unscheduled")
    await ctx.say(copy.UNSCHEDULED, draft)


async def save_draft(ctx: Ctx, draft: Draft) -> None:
    draft.status = S.SAVED
    if ctx.user.active_draft_id == draft.id:
        ctx.user.active_draft_id = None
    audit(ctx.session, ctx.user.id, draft.id, "human", "saved_draft")
    await ctx.say(copy.SAVED.format(url=dashboard_url(f"/app/drafts/{draft.id}")), draft)


async def retry(ctx: Ctx, draft: Draft) -> None:
    stage = draft.failed_stage or "edit"
    draft.error = None
    if stage == "publish":
        await publish_now(ctx, draft)
    elif stage == "captions":
        await start_captions(ctx, draft)
    elif draft.master_path:
        draft.status = S.REVISING
        await enqueue(ctx.session, "revise_video", draft_id=draft.id, payload={})
        await ctx.say(copy.RETRYING, draft)  # "revision 0 of 3" read oddly for a failed first edit
    else:
        draft.status = S.PROCESSING
        await enqueue(ctx.session, "process_video", draft_id=draft.id)
        await ctx.say(copy.RECEIVED, draft)


async def say_status(ctx: Ctx) -> None:
    draft = await active_draft(ctx)
    if draft is None:
        draft = await ctx.session.scalar(
            select(Draft).where(Draft.user_id == ctx.user.id).order_by(Draft.created_at.desc()).limit(1)
        )
    if draft is None:
        await ctx.say(copy.NO_DRAFT)
        return
    extra = ""
    if draft.status == S.SCHEDULED and draft.publish_at:
        extra = f" for {human_time(draft.publish_at.astimezone(user_tz(ctx.user)))}"
    if draft.status == S.PUBLISHED and draft.ig_permalink:
        extra = f": {draft.ig_permalink}"
    await ctx.say(copy.STATUS.format(status=copy.STATUS_LABELS.get(draft.status, draft.status), extra=extra), draft)


async def run_action(user_id: str, draft_id: str, action: Callable[..., Awaitable[None]], *args) -> Draft:
    """Run an engine action from the dashboard, with the same lock and channel as the chat."""
    async with _locks[user_id]:
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            draft = await session.get(Draft, draft_id)
            if user is None or draft is None or draft.user_id != user_id:
                raise LookupError("draft not found")
            ctx = Ctx(session, user, draft.channel, draft.chat_ref)
            await action(ctx, draft, *args)
            await session.commit()
            await session.refresh(draft)
            return draft
