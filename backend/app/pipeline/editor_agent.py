"""The AI video editor as a tool-using agent.

The LLM edits by calling editing tools on a working storyboard; every call is validated in code and answered with
a short result, so the model can check its work (preview_edit) and correct itself before calling finish. Rendering
is deterministic (FFmpeg / HyperFrames). Without any LLM, rule-based editing handles the same change requests.
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.config import settings
from app.integrations import claude, llm
from app.pipeline.cuts import keep_segments, map_span, normalize_word, output_duration
from app.pipeline.storyboard import Storyboard, fallback_storyboard, removed_word_set, validate_storyboard
from app.pipeline.styles import PRESETS, STYLE_ORDER

log = logging.getLogger(__name__)
MAX_STEPS = 10
MOTION_RE = re.compile(r"\b(motion|animat\w*|kinetic|brag)\b", re.IGNORECASE)

INT, NUM, STR, BOOL = {"type": "integer"}, {"type": "number"}, {"type": "string"}, {"type": "boolean"}


def _fn(name: str, description: str, properties: dict | None = None) -> dict:
    props = properties or {}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": props, "required": list(props)},
        },
    }


TOOLS = [
    _fn("remove_words", "Cut a range of words: false starts, repeated takes, apologies, off-topic rambling. Indices "
        "come from the numbered transcript and are inclusive. Filler words and long pauses are removed automatically.",
        {"start_word": INT, "end_word": INT, "reason": STR}),
    _fn("restore_words", "Undo an earlier cut for a word range.", {"start_word": INT, "end_word": INT}),
    _fn("trim", "Cut extra seconds from the very start and/or very end of the clip (0 leaves it as is).",
        {"start_seconds": NUM, "end_seconds": NUM}),
    _fn("set_style", "Visual style preset: " + "; ".join(f"{p.name} = {p.description}" for p in PRESETS.values()),
        {"style": {"type": "string", "enum": STYLE_ORDER}}),
    _fn("set_hook", "On-screen hook for the first 2.5 s: max 6 words, taken from what is said or shown, no invented "
        "facts. Empty string removes it.", {"text": STR}),
    _fn("set_end_card", "Closing card for the last 2 s: punchline (max 7 words) and optional call to action (only if "
        "the user or brand kit gives one). Empty strings remove it.", {"punchline": STR, "cta": STR}),
    _fn("highlight_words", "Words to emphasise in captions (numbers, key nouns, the promise). Replaces the previous "
        "list. Max 8.", {"word_indices": {"type": "array", "items": INT}}),
    _fn("add_emoji", "Pop an emoji on a word. Max 4 per video. Skip for serious or sensitive topics.",
        {"word_index": INT, "emoji": STR}),
    _fn("clear_emojis", "Remove all emoji pops."),
    _fn("set_framing", "How to make the clip vertical 9:16. crop: follow one centred, steady subject. blur_pad: keep "
        "the whole frame over a blurred backdrop (safe for groups, wide shots, on-screen text). auto: decide from face "
        "detection.", {"mode": {"type": "string", "enum": ["auto", "crop", "blur_pad"]}}),
    _fn("set_captions", "Word-by-word captions on or off, and where they sit.",
        {"enabled": BOOL, "position": {"type": "string", "enum": ["lower", "middle", "upper"]}}),
    _fn("set_music", "Soft music bed ducked under the voice. Good for promos and upbeat clips; skip for serious talks.",
        {"enabled": BOOL}),
    _fn("set_motion_graphics", "Animated motion layer (kinetic captions, zoom punches, emoji pops, end card). Takes "
        "minutes to render: enable only when the user asked for motion or animation.", {"enabled": BOOL}),
    _fn("preview_edit", "Check your work: returns the edited duration, current settings and the transcript that "
        "remains after all cuts."),
    _fn("ask_user", "Ask the creator one short question when something important is unclear. The edit still renders "
        "and the question is sent with it.", {"question": STR}),
    _fn("finish", "Call when the edit is complete. notes: 1-3 short sentences for the creator about judgement calls. "
        "scene: one sentence describing what the video shows.",
        {"notes": {"type": "array", "items": STR}, "scene": STR}),
]

SYSTEM = """You are the AI video editor inside a WhatsApp assistant that turns creators' raw phone clips into \
Instagram Reels (vertical 9:16). You edit by calling tools. Filler words, long pauses, audio cleanup, captions and the \
9:16 reframe are handled automatically; you make the editorial decisions.

How to work:
1. Read the numbered transcript and look at what the video shows.
2. Cut false starts, repeated takes, apologies and off-topic rambling with remove_words. Keep the core message; never \
cut more than needed.
3. Unless the user picked a style, choose one that fits the content and brand. Set a hook from what is said or shown, \
highlight the key words, add a few emoji only if the tone is light, choose framing, decide on music.
4. Add an end card when there is a clear takeaway.
5. Call preview_edit, check the remaining transcript still makes sense, fix anything wrong, then call finish.

Rules:
- Never invent facts: no prices, dates, offers, names or claims that are not in the transcript, the user's notes or \
the brand kit.
- When change requests are given, apply them exactly and keep everything else as it was.
- If something important is unclear, call ask_user once instead of guessing.
- You may call several tools in one turn."""


@dataclass
class EditorResult:
    storyboard: Storyboard
    from_ai: bool
    editor: str  # gemini | groq | claude | rules
    trace: list[str]
    motion: bool


def _words_text(words: list[dict], a: int, b: int, limit: int = 80) -> str:
    return " ".join(w["text"] for w in words[a : b + 1])[:limit]


def initial_state(previous: dict | None, style: str, n_words: int, *, locked: bool, motion_allowed: bool,
                  motion_on: bool) -> dict:
    state = fallback_storyboard(style, n_words).model_dump()
    if previous:
        state.update({k: v for k, v in previous.items() if k in state})
        state["remove_ranges"] = list(previous.get("remove_ranges") or [])
        state["emoji_moments"] = list(previous.get("emoji_moments") or [])
    if locked:
        state["style"] = style
    state.update({"_style_locked": locked, "_motion_allowed": motion_allowed, "_motion": motion_on})
    return state


def to_storyboard(state: dict, n_words: int, duration: float) -> Storyboard:
    data = {k: v for k, v in state.items() if not k.startswith("_")}
    return validate_storyboard(Storyboard.model_validate(data), n_words, duration)


def apply_tool(state: dict, name: str, args: dict, words: list[dict], duration: float) -> str:
    """Execute one editing tool against the working storyboard. Returns a short result; errors come back as text so
    the model can correct itself."""
    try:
        return _apply_tool(state, name, args or {}, words, duration)
    except KeyError as exc:
        return f"error: missing argument {exc}"
    except (ValueError, TypeError) as exc:
        return f"error: {exc}"


def _apply_tool(state: dict, name: str, args: dict, words: list[dict], duration: float) -> str:
    n = len(words)

    def idx(value) -> int:
        i = int(value)
        if not 0 <= i < n:
            raise ValueError(f"word index {i} out of range 0-{max(n - 1, 0)}")
        return i

    if name == "remove_words":
        a, b = sorted((idx(args["start_word"]), idx(args["end_word"])))
        already = len(removed_word_set(to_storyboard(state, n, duration)))
        if already + (b - a + 1) > n * 0.6:
            return "error: that would delete most of the video. Cut smaller, specific ranges."
        reason = str(args.get("reason") or "cut")[:80]
        state["remove_ranges"].append({"start_word": a, "end_word": b, "reason": reason})
        return f'ok: removed words {a}-{b}: "{_words_text(words, a, b)}"'
    if name == "restore_words":
        a, b = sorted((idx(args["start_word"]), idx(args["end_word"])))
        state["remove_ranges"] = [r for r in state["remove_ranges"] if r["end_word"] < a or r["start_word"] > b]
        return f"ok: restored words {a}-{b}"
    if name == "trim":
        cap = duration / 3
        state["trim_start_s"] = round(min(max(float(args.get("start_seconds") or 0), 0), cap), 2)
        state["trim_end_s"] = round(min(max(float(args.get("end_seconds") or 0), 0), cap), 2)
        return f"ok: trim start {state['trim_start_s']}s, end {state['trim_end_s']}s"
    if name == "set_style":
        style = str(args.get("style", "")).lower()
        if style not in PRESETS:
            return f"error: unknown style; use one of {', '.join(STYLE_ORDER)}"
        if state["_style_locked"] and style != state["style"]:
            return f"error: the user asked for the {state['style']} style; keep it"
        state["style"] = style
        return f"ok: style {style}"
    if name == "set_hook":
        text = " ".join(str(args.get("text", "")).split()[:6])[:40]
        state["hook_text"] = text
        return f'ok: hook "{text}"' if text else "ok: no hook"
    if name == "set_end_card":
        state["punchline_text"] = " ".join(str(args.get("punchline", "")).split()[:7])[:48]
        state["cta_text"] = " ".join(str(args.get("cta", "")).split()[:8])[:48]
        return f'ok: end card "{state["punchline_text"]}" / "{state["cta_text"]}"'
    if name == "highlight_words":
        picks = sorted({idx(i) for i in (args.get("word_indices") or [])})[:8]
        state["highlight_word_indices"] = picks
        return "ok: highlighting " + ", ".join(f'"{words[i]["text"]}"' for i in picks)
    if name == "add_emoji":
        if len(state["emoji_moments"]) >= 4:
            return "error: already 4 emoji"
        emoji = str(args.get("emoji", "")).strip()
        if not emoji or len(emoji) > 6 or any(ch.isascii() for ch in emoji):
            return "error: give a single emoji character"
        i = idx(args["word_index"])
        state["emoji_moments"].append({"word_index": i, "emoji": emoji})
        return f'ok: {emoji} on "{words[i]["text"]}"'
    if name == "clear_emojis":
        state["emoji_moments"] = []
        return "ok: emoji cleared"
    if name == "set_framing":
        mode = str(args.get("mode", "auto"))
        if mode not in {"auto", "crop", "blur_pad"}:
            return "error: mode must be auto, crop or blur_pad"
        state["crop_mode"] = mode
        return f"ok: framing {mode}"
    if name == "set_captions":
        position = str(args.get("position", "lower"))
        if position not in {"lower", "middle", "upper"}:
            position = "lower"
        state["captions_enabled"], state["caption_position"] = bool(args.get("enabled", True)), position
        return f"ok: captions {'on' if state['captions_enabled'] else 'off'} ({position})"
    if name == "set_music":
        state["music"] = bool(args.get("enabled"))
        return f"ok: music {'on' if state['music'] else 'off'}"
    if name == "set_motion_graphics":
        enabled = bool(args.get("enabled"))
        if enabled and not state["_motion_allowed"]:
            return "error: only enable motion graphics when the user asks for motion or animation"
        state["_motion"] = enabled
        return f"ok: motion graphics {'on' if enabled else 'off'}"
    if name == "preview_edit":
        sb = to_storyboard(state, n, duration)
        removed = removed_word_set(sb)
        segments = keep_segments(words, duration, removed, trim_start=sb.trim_start_s, trim_end=sb.trim_end_s)
        kept = [w["text"] for i, w in enumerate(words)
                if i not in removed and map_span(w["start"], w["end"], segments) is not None]
        return json.dumps({
            "duration_in": round(duration, 1),
            "duration_out": output_duration(segments),
            "style": sb.style, "hook": sb.hook_text, "end_card": sb.punchline_text,
            "captions": sb.captions_enabled, "framing": sb.crop_mode, "music": sb.music,
            "remaining_transcript": " ".join(kept)[:1500],
        })
    if name == "ask_user":
        state["question_for_user"] = str(args.get("question", ""))[:200]
        return "ok: question will be sent with the preview"
    if name == "finish":
        state["edit_notes"] = [str(x)[:120] for x in (args.get("notes") or [])][:3]
        state["scene_description"] = str(args.get("scene", ""))[:400]
        return "ok: finished"
    return f"error: unknown tool {name}"


def _trace_line(name: str, args: dict | None, result: str) -> str:
    shown = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in (args or {}).items())[:160]
    return f"{'✗ ' if result.startswith('error') else ''}{name}({shown})"


# ------------------------------------------------------------------ rule-based fallback (no LLM)

_STYLE_RE = re.compile(r"\b(" + "|".join(STYLE_ORDER) + r")\b")
_PHRASE_RE = re.compile(
    r"(?:cut|remove|delete|drop)(?: out)?(?: the)?(?: part| bit| section| line)?(?: where| when)? "
    r"(?:i|we|he|she|they) (?:say|said|says|mention|mentioned|talk about)s? [\"“']?(.+?)[\"”']?\s*$"
)


RESTART_MARKERS = ("let me start again", "let me start over", "start again", "start over", "let me try again",
                   "one more time", "take two", "scratch that", "let me redo", "wait wait")


def sentences(words: list[dict]) -> list[tuple[int, int]]:
    spans, start = [], 0
    for i, w in enumerate(words):
        if w["text"].endswith((".", "!", "?")) or i == len(words) - 1:
            spans.append((start, i))
            start = i + 1
    return spans


def auto_rules(state: dict, words: list[dict], duration: float) -> list[str]:
    """No-LLM editing pass: drop restart sentences ("sorry, let me start again") like an editor would."""
    trace: list[str] = []
    spans = sentences(words)

    def tokens(span: tuple[int, int]) -> set[str]:
        return {normalize_word(w["text"]) for w in words[span[0] : span[1] + 1]} - {""}

    def cut(span: tuple[int, int], reason: str) -> None:
        args = {"start_word": span[0], "end_word": span[1], "reason": reason}
        trace.append(_trace_line("remove_words", args, apply_tool(state, "remove_words", args, words, duration)))

    for k, span in enumerate(spans):
        text = " ".join(normalize_word(w["text"]) for w in words[span[0] : span[1] + 1])
        if not any(marker in text for marker in RESTART_MARKERS):
            continue
        if 0 < k < len(spans) - 1:  # the take before a restart usually repeats the take after it
            before, after = tokens(spans[k - 1]), tokens(spans[k + 1])
            if before and len(before & after) / len(before) >= 0.5:
                cut(spans[k - 1], "repeated take")
        cut(span, "false start")
    return trace


def find_phrase(words: list[dict], phrase: str) -> tuple[int, int] | None:
    tokens = [normalize_word(t) for t in phrase.split() if normalize_word(t)]
    norm = [normalize_word(w["text"]) for w in words]
    for i in range(len(words) - len(tokens) + 1):
        if tokens and norm[i : i + len(tokens)] == tokens:
            start, end = i, i + len(tokens) - 1
            while start > 0 and not words[start - 1]["text"].endswith((".", "!", "?")) and i - start < 12:
                start -= 1
            while end < len(words) - 1 and not words[end]["text"].endswith((".", "!", "?")) and end - i < 12:
                end += 1
            return start, end
    return None


def apply_rules(state: dict, notes: list[str], words: list[dict], duration: float) -> list[str]:
    trace: list[str] = []

    def run(name: str, **args) -> None:
        result = apply_tool(state, name, args, words, duration)
        trace.append(_trace_line(name, args, result))

    for raw in notes:
        t = raw.lower().strip()
        if re.search(r"\b(no|remove|without|drop|delete|lose)( the)? hook\b", t):
            run("set_hook", text="")
        elif m := re.search(r"\bhook\b\s*(?:to|:|=|says?|saying|should say)\s*[\"“']?([^\"”']{2,60})[\"”']?\s*$", raw,
                            re.IGNORECASE):
            run("set_hook", text=m.group(1))
        if m := re.search(r"(?:cut|remove|trim|drop)(?: the)? first (\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)\b", t):
            run("trim", start_seconds=float(m.group(1)), end_seconds=state["trim_end_s"])
        if m := re.search(r"(?:cut|remove|trim|drop)(?: the)? last (\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)\b", t):
            run("trim", start_seconds=state["trim_start_s"], end_seconds=float(m.group(1)))
        if re.search(r"\b(no|remove|without|hide|turn off)( the)? (captions|subtitles)\b", t):
            run("set_captions", enabled=False, position=state["caption_position"])
        elif "caption" in t or "subtitle" in t:
            for word, pos in (("top", "upper"), ("upper", "upper"), ("middle", "middle"), ("center", "middle"),
                              ("centre", "middle"), ("bottom", "lower"), ("lower", "lower")):
                if word in t:
                    run("set_captions", enabled=True, position=pos)
                    break
        if m := _STYLE_RE.search(t):
            run("set_style", style=m.group(1))
        if re.search(r"\b(no|remove|without|turn off|stop)( the)? music\b", t):
            run("set_music", enabled=False)
        elif re.search(r"\b(add|with|put)( some| a)?( background)? music\b", t):
            run("set_music", enabled=True)
        if MOTION_RE.search(t):
            run("set_motion_graphics", enabled=True)
        if re.search(r"\b(no|remove|without)( the)? (emoji|emojis)\b", t):
            run("clear_emojis")
        if re.search(r"\b(no|remove|without)( the)? end ?card\b", t):
            run("set_end_card", punchline="", cta="")
        if m := _PHRASE_RE.search(t):
            span = find_phrase(words, m.group(1))
            if span:
                run("remove_words", start_word=span[0], end_word=span[1], reason=f'removed "{m.group(1)[:40]}"')
            else:
                trace.append(f'✗ could not find "{m.group(1)[:40]}" in the transcript')
    return trace


# ------------------------------------------------------------------ the agent loop


def _prompt(*, words, probe, face_x, brand, user_context, style_request, motion_allowed, change_requests,
            previous) -> str:
    duration = float(probe["duration"])
    orientation = "landscape" if probe["width"] > probe["height"] else "vertical"
    face = f"one steady face at x={face_x:.2f} (0=left, 1=right)" if face_x is not None else "no single steady face"
    lines = [
        f"Clip: {duration:.1f} s, {probe['width']}x{probe['height']} {orientation}, audio: {'yes' if probe['has_audio'] else 'no'}.",
        f"Face detection: {face}.",
        f"Brand kit: {json.dumps(brand, ensure_ascii=False)}",
        f"User's notes about this video: {user_context or '(none)'}",
        f"Style: {'the user asked for ' + style_request if style_request else 'your choice'}.",
        f"Motion graphics: {'allowed (the user asked for it)' if motion_allowed else 'not requested'}.",
    ]
    if previous:
        keep = {k: previous.get(k) for k in ("style", "hook_text", "punchline_text", "cta_text", "remove_ranges",
                                            "highlight_word_indices", "emoji_moments", "crop_mode", "captions_enabled",
                                            "caption_position", "music", "trim_start_s", "trim_end_s")}
        lines.append(f"Current edit (revise it, keep what isn't asked to change): {json.dumps(keep, ensure_ascii=False)}")
    if change_requests:
        lines.append("Change requests from the user, oldest first: " + json.dumps(change_requests, ensure_ascii=False))
    transcript = " ".join(f"{i}:{w['text']}@{w['start']:.1f}" for i, w in enumerate(words)) or "(no speech detected)"
    lines.append("Transcript (index:word@seconds):\n" + transcript)
    return "\n".join(lines)


def _echo(message: dict) -> dict:
    """Assistant message as it must be sent back (keeps provider extras such as Gemini thought signatures)."""
    out = {k: v for k, v in message.items() if not k.startswith("_")}
    out["role"] = "assistant"
    if out.get("content") is None and not out.get("tool_calls"):
        out["content"] = ""
    return out


async def _agent(provider: llm.Provider, state: dict, frames: list[Path], prompt: str, words: list[dict],
                 duration: float) -> list[str]:
    content: list[dict] = [{"type": "text", "text": prompt}]
    if provider.max_images:
        content += [llm.image_part(f) for f in frames[: provider.max_images]]
    elif provider.vision_model and frames:
        visual = await llm.describe_frames(provider, frames)
        if visual:
            content[0]["text"] += f"\n\nWhat the frames show: {visual}"
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]
    trace: list[str] = []
    for _ in range(MAX_STEPS):
        reply = await llm.chat(provider, messages, tools=TOOLS, max_tokens=4000)
        calls = reply.get("tool_calls") or []
        messages.append(_echo(reply))
        if not calls:
            break
        finished = False
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
                result = apply_tool(state, name, args, words, duration)
            except json.JSONDecodeError:
                args, result = None, "error: arguments were not valid JSON"
            except (KeyError, ValueError, TypeError) as exc:
                args, result = args if isinstance(args, dict) else None, f"error: {exc}"
            trace.append(_trace_line(name, args, result))
            messages.append({"role": "tool", "tool_call_id": call.get("id", name), "name": name, "content": result})
            finished = finished or (name == "finish" and result.startswith("ok"))
        if finished:
            break
    if not trace:
        raise llm.LLMError(f"{provider.name} made no tool calls")
    return trace


async def run_editor(
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
    motion_requested: bool,
) -> EditorResult:
    duration = float(probe["duration"])
    style = style_request or (previous or {}).get("style") or brand.get("default_style") or "clean"
    motion_allowed = motion_requested or any(MOTION_RE.search(n) for n in change_requests)
    motion_on = motion_requested or bool((previous or {}).get("motion"))

    def fresh() -> dict:
        return initial_state(previous, style, len(words), locked=bool(style_request), motion_allowed=motion_allowed,
                             motion_on=motion_on)

    prompt = _prompt(words=words, probe=probe, face_x=face_x, brand=brand, user_context=user_context,
                     style_request=style_request, motion_allowed=motion_allowed, change_requests=change_requests,
                     previous=previous)
    for provider in llm.providers():
        state = fresh()
        try:
            trace = await _agent(provider, state, frames, prompt, words, duration)
            return EditorResult(to_storyboard(state, len(words), duration), True, provider.name, trace, state["_motion"])
        except (llm.LLMError, ValidationError, ValueError) as exc:
            log.warning("editor agent via %s failed: %s", provider.name, str(exc)[:300])

    if claude.enabled() and "anthropic" in settings.llm_providers:
        from app.pipeline.director import direct

        sb, from_ai = await direct(frames=frames, words=words, probe=probe, face_x=face_x, style_request=style_request,
                                   user_context=user_context, brand=brand, change_requests=change_requests,
                                   previous=previous)
        if from_ai:
            return EditorResult(sb, True, "claude", ["storyboard planned in one structured call"], motion_on)

    state = fresh()
    trace = [] if previous else auto_rules(state, words, duration)
    trace += apply_rules(state, change_requests[-1:] if previous else change_requests, words, duration)
    return EditorResult(to_storyboard(state, len(words), duration), False, "rules", trace, state["_motion"])
