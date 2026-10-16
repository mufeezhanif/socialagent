"""Claude as the editor-director: looks at frames + transcript, returns a Storyboard (JSON only)."""

import json
from pathlib import Path

from app.integrations import claude
from app.pipeline.storyboard import Storyboard, fallback_storyboard, validate_storyboard

SYSTEM = """You are the editor-director inside a WhatsApp video-editing assistant. Creators send raw phone clips; \
you decide how to cut and dress each one as an Instagram Reel (vertical 9:16). Work like a sharp short-form editor.

Rules:
- Keep the core message. Remove only false starts, repeated takes, apologies ("sorry, let me start again"), \
off-topic asides and rambling. Filler words (um, uh) and long pauses are removed automatically; do not list them.
- The hook must come from what is said or shown. Max 6 words. No clickbait lies.
- Never invent facts: no prices, dates, offers, names or claims that are not in the transcript or the user's notes.
- punchline_text lands the message at the end (max 7 words). cta_text only if the user's notes or brand kit give one.
- highlight_word_indices: up to 8 words that carry meaning (numbers, key nouns, the promise).
- emoji_moments: up to 4 emoji that match the moment (🔥 for a strong claim, 💰 for money, 😂 for a joke); none for \
serious or sensitive topics.
- style: pick what fits the content and brand tone, unless the user asked for a specific style - then use it.
- crop_mode: "crop" only for one clearly centred, steady subject; "blur_pad" for several people, wide shots, \
on-screen text or doubt; "auto" lets face detection decide.
- music: true for promos, montages and upbeat clips; false for serious talking pieces.
- If something important is unclear (which person to focus on, whether a section must stay, wrong language), \
write one short question in question_for_user instead of guessing.
- When change requests are given, apply them exactly and keep everything else from the previous storyboard.
- edit_notes: short, plain sentences about judgement calls (e.g. "Removed the restart at 0:12").
Word indices refer to the numbered transcript."""


def _transcript_block(words: list[dict]) -> str:
    if not words:
        return "(no speech detected)"
    return " ".join(f"{i}:{w['text']}@{w['start']:.1f}" for i, w in enumerate(words))


async def direct(
    *,
    frames: list[Path],
    words: list[dict],
    probe: dict,
    face_x: float | None,
    style_request: str | None,
    user_context: str | None,
    brand: dict,
    change_requests: list[str],
    previous: dict | None,
) -> tuple[Storyboard, bool]:
    """Returns (storyboard, from_ai). Falls back to a deterministic storyboard when Claude is unavailable."""
    duration = float(probe["duration"])
    default_style = style_request or brand.get("default_style") or "clean"
    orientation = "landscape" if probe["width"] > probe["height"] else "vertical"
    face = f"one steady face at x={face_x:.2f} (0=left, 1=right)" if face_x is not None else "no single steady face"
    lines = [
        f"Clip: {duration:.1f} s, {probe['width']}x{probe['height']} {orientation}, audio: {'yes' if probe['has_audio'] else 'no'}.",
        f"Face detection: {face}.",
        f"Brand kit: {json.dumps(brand, ensure_ascii=False)}",
        f"Requested style: {style_request or 'choose the best fit'}.",
        f"User notes about this video: {user_context or '(none)'}",
    ]
    if previous:
        lines.append(f"Previous storyboard (revise it): {json.dumps(previous, ensure_ascii=False)}")
    if change_requests:
        lines.append("Change requests, oldest first: " + json.dumps(change_requests, ensure_ascii=False))
    lines.append("Transcript (index:word@seconds):\n" + _transcript_block(words))

    content: list = [claude.image_block(f) for f in frames[:8]]
    content.append({"type": "text", "text": "\n".join(lines)})

    result = await claude.parse(Storyboard, system=SYSTEM, content=content, effort="medium")
    if result is None:
        sb = fallback_storyboard(default_style, len(words))
        if previous:
            sb = Storyboard.model_validate({"emoji_moments": [], **previous, "style": default_style})
        return validate_storyboard(sb, len(words), duration), False
    if style_request:
        result.style = style_request  # an explicit user request always wins
    return validate_storyboard(result, len(words), duration), True
