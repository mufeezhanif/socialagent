"""Caption pack: 3 options + hashtags + facts the creator should double-check."""

import json
import re
from typing import Literal

from pydantic import BaseModel

from app.integrations import llm

IG_CAPTION_LIMIT = 2200
MAX_HASHTAGS = 15
GENERIC_TAGS = ["reels", "reelsinstagram", "instagood", "contentcreator", "explorepage"]


class CaptionOption(BaseModel):
    style: Literal["hook", "story", "short"]
    text: str


class CaptionPack(BaseModel):
    options: list[CaptionOption]
    hashtags: list[str]
    facts_to_confirm: list[str]


SYSTEM = """You write Instagram Reel captions for a creator. Write exactly 3 options:
1. hook: a bold first line that stops the scroll, then 1-2 short lines.
2. story: 2-4 short lines with a personal angle.
3. short: one punchy line.

Rules:
- Write in the creator's voice and in the language they speak in the transcript.
- Use only facts from the transcript, the user's notes and the brand kit. Never invent prices, dates, offers,
  locations, names or claims. If a detail is missing, leave it out.
- Emoji use follows the brand kit's emoji level (none / some / lots).
- End with the brand CTA if one is given. No hashtags inside the caption text.
- hashtags: 8-15 relevant tags mixing broad, niche and local ones; no '#' symbol, no spaces.
- facts_to_confirm: every concrete claim you used (numbers, prices, dates, offers) so the creator can double-check;
  empty list if none.
- When a tweak request is given, rewrite accordingly and keep what the creator liked."""


def clean_tag(tag: str) -> str:
    return re.sub(r"[^\w]", "", tag.lstrip("#")).lower()


def _strip_banned(text: str, banned: list[str]) -> str:
    for word in banned:
        if word.strip():
            text = re.sub(re.escape(word.strip()), "", text, flags=re.IGNORECASE)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def validate_pack(pack: CaptionPack, brand: dict) -> dict:
    banned = brand.get("banned_words") or []
    tags: list[str] = []
    for tag in (brand.get("default_hashtags") or []) + pack.hashtags:
        cleaned = clean_tag(tag)
        if cleaned and cleaned not in tags and cleaned not in {clean_tag(b) for b in banned}:
            tags.append(cleaned)
    tags = tags[:MAX_HASHTAGS]
    tag_len = sum(len(t) + 2 for t in tags)
    options = []
    for opt in pack.options[:3]:
        text = _strip_banned(opt.text, banned)[: IG_CAPTION_LIMIT - tag_len - 4]
        options.append({"style": opt.style, "text": text})
    while len(options) < 3:
        options.append({"style": "short", "text": options[0]["text"] if options else "New video 🎬"})
    return {"options": options, "hashtags": tags, "facts_to_confirm": pack.facts_to_confirm[:5]}


def fallback_pack(transcript_text: str, storyboard: dict, brand: dict) -> dict:
    from app.pipeline.cuts import is_filler

    transcript_text = " ".join(w for w in transcript_text.split() if not is_filler(w))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript_text) if s.strip()]
    first = sentences[0] if sentences else "New video is up 🎬"
    hook = storyboard.get("hook_text") or first
    pack = CaptionPack(
        options=[
            CaptionOption(style="hook", text=f"{hook} 👇\n\n" + " ".join(sentences[1:3])),
            CaptionOption(style="story", text=" ".join(sentences[:4]) or first),
            CaptionOption(style="short", text=storyboard.get("punchline_text") or first),
        ],
        hashtags=GENERIC_TAGS,
        facts_to_confirm=[],
    )
    return validate_pack(pack, brand)


VISUAL_KEYS = {"accent_color", "default_style", "handle"}  # render-only settings, no use to the caption writer


async def generate(
    *,
    transcript_text: str,
    storyboard: dict,
    user_context: str | None,
    brand: dict,
    previous_pack: dict | None = None,
    tweak: str | None = None,
) -> tuple[dict, bool]:
    """Returns (pack, from_ai)."""
    lines = [
        f"Transcript: {transcript_text or '(no speech)'}",
        f"What the video shows: {storyboard.get('scene_description') or '(unknown)'}",
        f"On-screen hook: {storyboard.get('hook_text') or '(none)'}",
        f"User notes: {user_context or '(none)'}",
        f"Brand kit: {json.dumps({k: v for k, v in brand.items() if v and k not in VISUAL_KEYS | {"learned_style"}}, ensure_ascii=False)}",
    ]
    if brand.get("learned_style"):
        lines.append("Creator's learned preferences (follow them): " + "; ".join(brand["learned_style"]))
    if previous_pack and tweak:
        lines.append(f"Previous options: {json.dumps(previous_pack.get('options'), ensure_ascii=False)}")
        lines.append(f"Tweak request: {tweak}")
    pack = await llm.structured(CaptionPack, system=SYSTEM, text="\n".join(lines), effort="medium")
    if pack is None or not pack.options:
        return fallback_pack(transcript_text, storyboard, brand), False
    return validate_pack(pack, brand), True


def full_caption(caption: str, hashtags: list[str]) -> str:
    tags = " ".join(f"#{t}" for t in hashtags)
    return f"{caption}\n\n{tags}".strip()[:IG_CAPTION_LIMIT]
