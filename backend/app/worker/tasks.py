"""Job handlers. Each one reads state, does slow work without holding a DB transaction, then writes results."""

import logging
import time
from pathlib import Path

from sqlalchemy import select

from app.agent import copy
from app.agent.engine import Ctx, InboundEvent, brand_dict, draft_dir, get_brand, handle_inbound
from app.config import settings
from app.db import SessionLocal
from app.models import Draft, DraftStatus as S, InstagramAccount, Job, User, utcnow
from app.pipeline.edit import EditInput, EditOutput, run_edit
from app.pipeline.probe import probe
from app.pipeline.render_hyperframes import hyperframes_available
from app.pipeline.styles import get_preset
from app.services import captions, messaging, publisher, taste
from app.services.audit import audit

log = logging.getLogger(__name__)


async def _load(draft_id: str) -> tuple[Draft, User, dict] | None:
    async with SessionLocal() as session:
        draft = await session.get(Draft, draft_id)
        if draft is None:
            return None
        user = await session.get(User, draft.user_id)
        brand = brand_dict(await get_brand(session, draft.user_id))
        handle = await session.scalar(select(InstagramAccount.username).where(InstagramAccount.user_id == draft.user_id))
        if handle:
            brand["handle"] = handle  # shown on brand name tags and end cards
        learned = await taste.notes_for(session, draft.user_id)
        if learned:
            brand["learned_style"] = learned  # the editor and caption prompts read every brand key
        await session.commit()
        return draft, user, brand


async def _fail(draft_id: str, stage: str, human_stage: str, error: str) -> None:
    async with SessionLocal() as session:
        draft = await session.get(Draft, draft_id)
        user = await session.get(User, draft.user_id)
        draft.status, draft.failed_stage, draft.error = S.FAILED, stage, error[:1000]
        audit(session, user.id, draft.id, "system", "failed", stage=stage, error=error[:300])
        await Ctx(session, user, draft.channel, draft.chat_ref).say(copy.FAILED.format(stage=human_stage), draft)
        await session.commit()


async def inbound(job: Job) -> None:
    await handle_inbound(InboundEvent(**job.payload))


async def _send_preview(ctx: Ctx, draft: Draft, result: EditOutput) -> None:
    preset = get_preset(result.storyboard.get("style"))
    await ctx.say(f"✨ Edit ready ({result.duration_in:.0f}s → {result.duration_out:.0f}s)", draft, video=result.preview)
    text = copy.EDIT_READY.format(
        din=f"{result.duration_in:.0f}",
        dout=f"{result.duration_out:.0f}",
        style=preset.label,
        bullets="\n".join(f"• {b}" for b in result.summary),
    ) + copy.approval_options(hyperframes_available())
    if result.question:
        text += copy.QUESTION.format(question=result.question)
    await ctx.say(text, draft)


async def _edit(job: Job, *, revision_mode: bool) -> None:
    loaded = await _load(job.draft_id)
    if loaded is None:
        return
    draft, user, brand = loaded
    expected = S.REVISING if revision_mode else S.PROCESSING

    probe_data = draft.probe
    if not probe_data:
        try:
            info = await probe(draft.source_path)
        except Exception as exc:
            await _fail(draft.id, "edit", "reading your video", str(exc))
            return
        if info.duration > settings.max_video_seconds or info.duration < 2.5:
            async with SessionLocal() as session:
                d = await session.get(Draft, draft.id)
                d.status = S.DISCARDED
                msg = (copy.TOO_LONG if info.duration > settings.max_video_seconds else copy.TOO_SHORT).format(
                    dur=f"{info.duration:.0f}", max=settings.max_video_seconds
                )
                await Ctx(session, user, d.channel, d.chat_ref).say(msg, d)
                await session.commit()
            return
        probe_data = info.to_dict()

    await messaging.typing(draft.channel, draft.chat_ref)
    style_request = (job.payload or {}).get("style")
    motion = bool((job.payload or {}).get("motion") or (revision_mode and (draft.probe or {}).get("motion")))
    new_revision = draft.revision + 1 if revision_mode else draft.revision
    started = time.time()
    try:
        result = await run_edit(
            EditInput(
                src=Path(draft.source_path),
                workdir=draft_dir(user.id, draft.id) / f"r{new_revision}",
                style_request=style_request,
                user_context=draft.user_context,
                brand=brand,
                change_requests=list(draft.revision_notes or []) if revision_mode else [],
                previous_storyboard=draft.storyboard if revision_mode else None,
                probe=probe_data,
                transcript=draft.transcript,
                face_x=(draft.probe or {}).get("face_x"),
                face_checked="face_x" in (draft.probe or {}),
                motion=motion,
            )
        )
    except Exception as exc:
        log.exception("edit failed for %s", draft.id)
        await _fail(draft.id, "edit", "editing your video", str(exc))
        return

    async with SessionLocal() as session:
        d = await session.get(Draft, draft.id)
        tried = list((d.probe or {}).get("styles_tried") or [])
        if result.storyboard["style"] not in tried:
            tried.append(result.storyboard["style"])
        d.probe = {**result.probe, "face_x": result.face_x, "styles_tried": tried, "motion": result.motion}
        d.transcript = result.transcript
        d.storyboard = {**result.storyboard, "trace": result.trace, "editor": result.editor,
                        **({"critic": result.critic} if result.critic else {})}
        d.style = result.storyboard["style"]
        d.edit_summary = result.summary
        d.master_path, d.preview_path, d.cover_path = str(result.master), str(result.preview), str(result.cover)
        d.duration_in, d.duration_out = result.duration_in, result.duration_out
        d.revision = new_revision
        audit(
            session, user.id, d.id, "ai", "edited_video",
            revision=new_revision, style=d.style, seconds=round(time.time() - started, 1),
            summary=result.summary, director=result.editor, tools=len(result.trace),
        )
        if result.critic:
            audit(
                session, user.id, d.id, "ai", "critic_review", agent="critic",
                verdict=result.critic["verdict"], revised=result.critic["revised"],
                issues=[i["problem"] for i in result.critic["issues"]],
            )
        if d.status == expected:  # the user may have moved on (sent a new video, discarded)
            d.status = S.AWAITING_VIDEO_APPROVAL
            await _send_preview(Ctx(session, user, d.channel, d.chat_ref), d, result)
        await session.commit()


async def process_video(job: Job) -> None:
    await _edit(job, revision_mode=False)


async def revise_video(job: Job) -> None:
    await _edit(job, revision_mode=True)


async def caption_pack(job: Job) -> None:
    loaded = await _load(job.draft_id)
    if loaded is None:
        return
    draft, user, brand = loaded
    await messaging.typing(draft.channel, draft.chat_ref)
    tweak = (job.payload or {}).get("tweak")
    words = (draft.transcript or {}).get("words") or []
    removed = set()
    for r in (draft.storyboard or {}).get("remove_ranges") or []:
        removed.update(range(r["start_word"], r["end_word"] + 1))
    kept_text = " ".join(w["text"] for i, w in enumerate(words) if i not in removed)
    try:
        pack, from_ai = await captions.generate(
            transcript_text=kept_text,
            storyboard=draft.storyboard or {},
            user_context=draft.user_context,
            brand=brand,
            previous_pack=draft.caption_pack,
            tweak=tweak,
        )
    except Exception as exc:
        log.exception("captions failed for %s", draft.id)
        await _fail(draft.id, "captions", "writing captions", str(exc))
        return
    async with SessionLocal() as session:
        d = await session.get(Draft, draft.id)
        d.caption_pack = pack
        audit(session, user.id, d.id, "ai", "wrote_captions", tweak=tweak, writer="ai" if from_ai else "fallback")
        if d.status == S.CAPTIONING:
            d.status = S.AWAITING_CAPTION_CHOICE
            opts = pack["options"]
            text = copy.CAPTION_OPTIONS.format(
                c1=opts[0]["text"], c2=opts[1]["text"], c3=opts[2]["text"],
                tags=" ".join(f"#{t}" for t in pack["hashtags"]),
            )
            if pack.get("facts_to_confirm"):
                text += copy.FACT_CHECK.format(facts="; ".join(pack["facts_to_confirm"]))
            await Ctx(session, user, d.channel, d.chat_ref).say(text + copy.CAPTION_REPLY, d)
        await session.commit()


_publishing: set[str] = set()  # draft ids mid-publish in this (single) worker process


async def publish(job: Job) -> None:
    # a scheduler tick racing a dashboard "post now" can queue two jobs (different dedupe keys); post once
    if job.draft_id in _publishing:
        return
    _publishing.add(job.draft_id)
    try:
        await _publish(job)
    finally:
        _publishing.discard(job.draft_id)


async def _publish(job: Job) -> None:
    async with SessionLocal() as session:
        draft = await session.get(Draft, job.draft_id)
        if draft is None or draft.status != S.PUBLISHING:
            return
        user = await session.get(User, draft.user_id)
        ctx = Ctx(session, user, draft.channel, draft.chat_ref)
        try:
            media_id, permalink = await publisher.publish(session, draft)
        except publisher.GateError as exc:
            draft.status = S.AWAITING_PUBLISH_CHOICE
            audit(session, user.id, draft.id, "system", "publish_blocked", reason=str(exc))
            await ctx.say(f"⛔ I can't post this yet: {exc}.\n\n" + copy.ASK_PUBLISH, draft)
            await session.commit()
            return
        except Exception as exc:
            log.warning("publish failed for %s: %s", draft.id, exc)
            draft.status, draft.failed_stage, draft.error = S.FAILED, "publish", str(exc)[:1000]
            audit(session, user.id, draft.id, "system", "publish_failed", error=str(exc)[:300])
            await ctx.say(copy.PUBLISH_FAILED.format(error=str(exc)[:200]), draft)
            await session.commit()
            return
        draft.ig_media_id, draft.ig_permalink, draft.status = media_id, permalink, S.PUBLISHED
        if user.active_draft_id == draft.id:
            user.active_draft_id = None
        audit(session, user.id, draft.id, "ai", "published", permalink=permalink, at=utcnow().isoformat())
        await ctx.say(copy.PUBLISHED.format(permalink=permalink), draft)
        await session.commit()


HANDLERS = {
    "inbound": inbound,
    "process_video": process_video,
    "revise_video": revise_video,
    "caption_pack": caption_pack,
    "publish": publish,
    "learn_taste": taste.learn,
}
HEAVY = {"process_video", "revise_video"}
