"""Turn a user's reply into an intent: numbers and keywords first, Claude only for free text."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.integrations import claude
from app.pipeline.styles import STYLE_ORDER

APPROVE_WORDS = {"1", "approve", "approved", "yes", "y", "ok", "okay", "good", "great", "perfect", "love it",
                 "looks good", "nice", "done", "👍", "✅", "👌", "❤️", "🔥", "go", "go ahead"}
DISCARD_WORDS = {"4", "discard", "delete", "trash", "drop it", "no thanks"}
SKIP_WORDS = {"skip", "no", "nope", "none", "nothing", "n/a", "na", "-", "no thanks", "nah"}
MOTION_WORDS = {"5", "motion", "motion graphics", "animate", "animate it", "animated", "brag", "make it pop", "✨"}
LIKE_REACTIONS = {"👍", "❤️", "❤", "🔥", "✅", "👌", "😍", "💯"}


@dataclass
class Intent:
    name: str
    data: dict = field(default_factory=dict)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().rstrip(".!"))


def _style_in(text: str) -> str | None:
    for style in STYLE_ORDER:
        if re.search(rf"\b{style}\b", text):
            return style
    return None


class ApprovalReply(BaseModel):
    intent: Literal["approve", "change", "style", "discard", "unclear"]
    notes: str  # the change request, rewritten as a clear instruction in English
    style: str  # requested style name, or ""


class CaptionReply(BaseModel):
    intent: Literal["choose", "own_caption", "tweak", "unclear"]
    option: int  # 1-3 when choosing or tweaking a specific option, else 0
    text: str  # the user's own caption, or the tweak instruction


class TimeReply(BaseModel):
    understood: bool
    iso_datetime: str  # ISO 8601 with UTC offset, in the user's timezone


async def approval(text: str) -> Intent:
    t = _norm(text)
    if t in APPROVE_WORDS:
        return Intent("approve")
    if t in DISCARD_WORDS:
        return Intent("discard")
    if t in MOTION_WORDS:
        return Intent("motion")
    if t == "2":
        return Intent("change")
    if t.startswith("2 ") or t.startswith("2."):
        return Intent("change", {"notes": text.strip()[2:].strip()})
    if t == "3" or t in {"another style", "different style", "new style"}:
        return Intent("style")
    style = _style_in(t)
    if style and len(t.split()) <= 5:
        return Intent("style", {"style": style})
    result = await claude.parse(
        ApprovalReply,
        system=(
            "Classify a creator's reply to an edited video preview. approve = they are happy; change = they want an edit "
            "(put the instruction in notes); style = they want a different look (style is one of: "
            + ", ".join(STYLE_ORDER) + " or empty); discard = throw it away; unclear = anything else."
        ),
        content=text,
        effort="low",
        max_tokens=2000,
    )
    if result is None:
        return Intent("change", {"notes": text.strip()}) if len(t) > 3 else Intent("unclear")
    if result.intent == "style":
        return Intent("style", {"style": result.style if result.style in STYLE_ORDER else ""})
    if result.intent == "change":
        return Intent("change", {"notes": result.notes or text.strip()})
    return Intent(result.intent)


def context(text: str) -> Intent:
    t = _norm(text)
    return Intent("skip") if t in SKIP_WORDS else Intent("context", {"text": text.strip()})


async def caption(text: str) -> Intent:
    t = _norm(text)
    m = re.fullmatch(r"(?:option\s*|#)?([123])", t)
    if m:
        return Intent("choose", {"option": int(m.group(1))})
    result = await claude.parse(
        CaptionReply,
        system=(
            "A creator was shown 3 numbered caption options for an Instagram Reel. Classify their reply: choose (picked an "
            "option), own_caption (they wrote the caption themselves; copy it exactly into text), tweak (they want changes; "
            "put the instruction in text and the option number if they named one), unclear."
        ),
        content=text,
        effort="low",
        max_tokens=2000,
    )
    if result is None:
        return Intent("own_caption", {"text": text.strip()}) if len(t) > 25 else Intent("unclear")
    return Intent(result.intent, {"option": result.option, "text": result.text})


def publish_choice(text: str) -> Intent:
    t = _norm(text)
    if t in {"1", "now", "post", "post now", "post it", "publish", "🚀"}:
        return Intent("now")
    if t in {"3", "save", "draft", "save draft", "save as draft", "later", "💾"}:
        return Intent("save")
    if t == "2" or t.startswith("schedule") or t == "🗓":
        rest = t.removeprefix("2").removeprefix("schedule").strip()
        return Intent("schedule", {"when": rest} if rest else {})
    return Intent("unclear")


async def schedule_time(text: str, now_local: datetime) -> datetime | None:
    from app.agent.timeparse import parse_time

    parsed = parse_time(text, now_local)
    if parsed:
        return parsed
    result = await claude.parse(
        TimeReply,
        system=(
            "Convert the user's requested posting time into an ISO 8601 datetime with UTC offset. "
            f"Current local time is {now_local.isoformat()} ({now_local.tzname()}). Interpret times in that timezone. "
            "Set understood=false if it is not a time."
        ),
        content=text,
        effort="low",
        max_tokens=1500,
    )
    if not result or not result.understood:
        return None
    try:
        value = datetime.fromisoformat(result.iso_datetime)
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=now_local.tzinfo)
