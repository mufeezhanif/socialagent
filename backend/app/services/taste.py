"""Taste memory: learns the creator's preferences from their own decisions (change requests, caption picks)."""

import logging
import re
from collections import Counter

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.integrations import llm
from app.models import AuditEvent, Draft, Job, TasteMemory, utcnow
from app.services.audit import audit
from app.worker.queue import enqueue

log = logging.getLogger(__name__)

SIGNAL_ACTIONS = ("requested_changes", "requested_style", "chose_caption", "wrote_caption", "discarded", "approved_edit")
MIN_SIGNALS = 2
MAX_NOTES = 8  # what the creator may keep (the API enforces the same)
MAX_LEARNED = 6  # what one learning pass may produce
MAX_LINE = 120
MAX_NEW_SIGNALS = 40

SYSTEM = """You maintain a short "taste memory" for a social media creator: preferences learned from the creator's OWN
decisions on AI-made Instagram Reel drafts. The notes steer future edits and captions.

You get the current notes and a list of new signals (what the creator asked for, picked, wrote or rejected).
Return the updated notes: at most 6 short, durable, concrete lines, each under 100 characters, for example
"Keeps Reels around 30 s", "Prefers a short punchy hook", "No emojis in captions", "Uses Urdu-English mix in captions".

Rules:
- Never invent a preference that is not supported by at least one signal or an existing note.
- Drop one-off, draft-specific requests (e.g. "remove the part about Tuesday"); keep only habits that would apply to
  any future video.
- Merge duplicates and near-duplicates into one line.
- Keep every existing note unless newer signals contradict it. Existing notes may have been written or edited by the
  creator themselves; treat them as truth.
- If there is nothing durable to learn, return the existing notes unchanged."""


class TasteOut(BaseModel):
    notes: list[str]


def clean_notes(lines, limit: int = MAX_NOTES) -> list[str]:
    """Stripped, non-empty, <=120 chars, de-duplicated (case-insensitive)."""
    out: list[str] = []
    for line in lines or []:
        text = re.sub(r"\s+", " ", str(line)).strip()[:MAX_LINE].strip()
        if text and text.lower() not in {o.lower() for o in out}:
            out.append(text)
    return out[:limit]


async def notes_for(session: AsyncSession, user_id: str) -> list[str]:
    """The learned lines handed to the editor and caption writer, or [] if nothing has been learned yet."""
    memory = await session.get(TasteMemory, user_id)
    return list(memory.notes or []) if memory else []


async def signal_count(session: AsyncSession, user_id: str) -> int:
    return await session.scalar(
        select(func.count(AuditEvent.id)).where(
            AuditEvent.user_id == user_id, AuditEvent.actor == "human", AuditEvent.action.in_(SIGNAL_ACTIONS)
        )
    ) or 0


async def queue_learning(session: AsyncSession, user_id: str, draft_id: str | None = None) -> None:
    """Called after a human decision: queue one learning pass (never more than one waiting per user). Never raises."""
    try:
        total = await signal_count(session, user_id)
        if total < MIN_SIGNALS:
            return
        waiting = await session.scalar(
            select(Job.id).where(
                Job.kind == "learn_taste", Job.status == "queued", Job.dedupe_key.like(f"learn:{user_id}:%")
            ).limit(1)
        )
        if waiting:
            return
        # keyed on the signal count: a new decision after the last run gets a new key, the same one never repeats
        await enqueue(
            session, "learn_taste", payload={"user_id": user_id, "draft_id": draft_id}, dedupe_key=f"learn:{user_id}:{total}"
        )
    except Exception:
        log.exception("could not queue taste learning for %s", user_id)


async def _signals(session: AsyncSession, user_id: str) -> list[dict]:
    """Every human decision, oldest first, as small dicts (caption text pulled from the draft where useful)."""
    events = (
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.user_id == user_id, AuditEvent.actor == "human", AuditEvent.action.in_(SIGNAL_ACTIONS))
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
    ).all()
    drafts: dict[str, Draft | None] = {}
    out = []
    for ev in events:
        d = ev.detail or {}
        sig: dict = {"type": ev.action}
        if ev.action == "requested_changes":
            sig["request"] = str(d.get("notes") or "")[:300]
        elif ev.action == "requested_style":
            sig["style"] = d.get("style")
        elif ev.action in ("chose_caption", "wrote_caption"):
            if ev.draft_id and ev.draft_id not in drafts:
                drafts[ev.draft_id] = await session.get(Draft, ev.draft_id)
            draft = drafts.get(ev.draft_id) if ev.draft_id else None
            if ev.action == "chose_caption":
                sig["option"] = d.get("option")
            if draft and draft.caption_final:
                sig["caption" if ev.action == "chose_caption" else "own_caption"] = draft.caption_final[:400]
        out.append(sig)
    return out


def rule_based(existing: list[str], signals: list[dict]) -> list[str]:
    """Tiny offline learner: only patterns repeated across the creator's own requests."""
    requests = [s.get("request", "").lower() for s in signals if s["type"] == "requested_changes"]
    found: list[str] = []
    if sum(1 for r in requests if re.search(r"\bno\s+emojis?\b|\b(remove|without|less|drop)\s+(the\s+)?emojis?\b", r)) >= 2:
        found.append("No emojis in captions")
    lengths = Counter(m.group(1) for r in requests for m in [re.search(r"\b(\d{2,3})\s*(?:s|sec|secs|seconds)\b", r)] if m)
    if lengths and lengths.most_common(1)[0][1] >= 2:
        found.append(f"Keeps Reels around {lengths.most_common(1)[0][0]} s")
    elif sum(1 for r in requests if re.search(r"\b(shorter|trim|too long|cut it down)\b", r)) >= 2:
        found.append("Prefers shorter Reels")
    styles = Counter(s["style"] for s in signals if s["type"] == "requested_style" and s.get("style"))
    if styles and styles.most_common(1)[0][1] >= 2:
        found.append(f"Likes the {styles.most_common(1)[0][0]} style")
    have = {n.lower() for n in existing}
    return clean_notes([*existing, *[f for f in found if f.lower() not in have]])


async def _llm_notes(existing: list[str], signals: list[dict]) -> list[str] | None:
    lines = [f"- {s}" for s in signals[-MAX_NEW_SIGNALS:]]
    text = "Current notes:\n" + ("\n".join(f"- {n}" for n in existing) or "(none)") + "\n\nNew signals:\n" + "\n".join(lines)
    result = await llm.structured(TasteOut, system=SYSTEM, text=text, effort="low", max_tokens=800)
    if result is None:
        return None
    return clean_notes(result.notes, MAX_LEARNED if len(existing) <= MAX_LEARNED else MAX_NOTES)


async def learn(job: Job) -> None:
    """Job handler for 'learn_taste' (light lane). Never raises: a failed pass just retries on the next decision."""
    try:
        user_id = (job.payload or {}).get("user_id")
        if not user_id:
            return
        async with SessionLocal() as session:
            signals = await _signals(session, user_id)
            memory = await session.get(TasteMemory, user_id)
            seen = memory.signals_seen if memory else 0
            existing = list(memory.notes or []) if memory else []
            if len(signals) < MIN_SIGNALS or len(signals) <= seen:
                return
            fresh = signals[seen:]
            if llm.any_configured():
                notes = await _llm_notes(existing, fresh)
                if notes is None:
                    return  # provider failed: leave signals_seen alone so the next decision tries again
            else:
                notes = rule_based(existing, signals)
            added = [n for n in notes if n.lower() not in {e.lower() for e in existing}]
            if memory is None:
                memory = TasteMemory(user_id=user_id)
                session.add(memory)
            memory.notes, memory.signals_seen, memory.updated_at = notes, len(signals), utcnow()
            if notes != existing:
                draft_id = (job.payload or {}).get("draft_id")  # the decision that triggered this pass, for its timeline
                audit(session, user_id, draft_id, "ai", "learned_taste", agent="memory", notes=added, total=len(notes))
            await session.commit()
    except Exception:
        log.exception("taste learning failed")
