"""The AI video editor as a tool-using agent.

The LLM edits by calling editing tools on a working storyboard; every call is validated in code and answered with
a short result, so the model can check its work (preview_edit) and correct itself before calling finish. Rendering
is deterministic (FFmpeg / HyperFrames). Without any LLM, rule-based editing handles the same change requests.
"""

import json
from collections import Counter
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.integrations import llm
from app.pipeline.cuts import FILLERS, keep_segments, map_span, normalize_word, output_duration
from app.pipeline.genres import RECIPES, VIDEO_TYPES, classify, get_recipe, type_from_request
from app.pipeline.storyboard import Storyboard, fallback_storyboard, removed_word_set, validate_storyboard
from app.pipeline.styles import PRESETS, STYLE_ORDER

log = logging.getLogger(__name__)
MAX_STEPS = 6
MOTION_RE = re.compile(r"\b(motion|animat\w*|kinetic|brag)\b", re.IGNORECASE)

INT, NUM, STR, BOOL = {"type": "integer"}, {"type": "number"}, {"type": "string"}, {"type": "boolean"}


def _fn(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    props = properties or {}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": props,
                           "required": list(props) if required is None else required},
        },
    }


# Kept short on purpose: the tool list is sent with every turn, so each word here is paid for several times per edit.
TOOLS = [
    _fn("remove_words", "Cut words start..end (inclusive). Fillers and pauses are cut automatically.",
        {"start_word": INT, "end_word": INT, "reason": STR}),
    _fn("restore_words", "Undo cuts in start..end.", {"start_word": INT, "end_word": INT}),
    _fn("trim", "Seconds to cut from the very start / end (0 = none).", {"start_seconds": NUM, "end_seconds": NUM}),
    _fn("set_look", "Video type picks music, sound effects and graphics: "
        + "; ".join(f"{r.name}: {r.description}" for r in RECIPES.values())
        + ". Style (optional): " + ", ".join(STYLE_ORDER) + ". Give only the fields you change.",
        {"video_type": {"type": "string", "enum": VIDEO_TYPES}, "style": {"type": "string", "enum": STYLE_ORDER},
         "music": BOOL, "framing": {"type": "string", "enum": ["auto", "crop", "blur_pad"]},
         "captions": {"type": "string", "enum": ["lower", "middle", "upper", "off"]}, "motion": BOOL}, []),
    _fn("set_text", "On-screen English text from what is said or shown. hook: first 2.5 s, max 6 words. punchline: "
        "end card, max 7 words. cta: only if the user or brand gives one. Empty string removes.",
        {"hook": STR, "punchline": STR, "cta": STR}, []),
    _fn("emphasize", "Replace caption highlights (max 8 key words) and emoji pops (max 4, light topics only).",
        {"words": {"type": "array", "items": INT},
         "emoji": {"type": "array", "items": {"type": "object", "properties": {"word": INT, "emoji": STR},
                                              "required": ["word", "emoji"]}}}, []),
    _fn("preview_edit", "Edited length and the transcript left after cuts."),
    _fn("finish", "Done. notes: 1-3 short notes for the creator. scene: one sentence on what the video shows. "
        "question: only if something important is unclear.",
        {"notes": {"type": "array", "items": STR}, "scene": STR, "question": STR}, ["notes", "scene"]),
]

SYSTEM = """You edit raw phone clips into Instagram Reels (9:16) by calling tools. Filler words, pauses, audio \
cleanup, captions and reframing are automatic; you make the editorial calls.

Finish in two turns:
1. Make every decision at once: remove_words for false starts, repeated takes, apologies and off-topic parts (cut \
whole sentences; never leave a fragment shorter than 2 s between cuts); set_look (video type; style only if the user \
did not choose one); set_text; emphasize; then preview_edit.
2. Fix anything wrong in the preview, then finish.

Rules: never invent facts (prices, dates, names, offers, claims) that are not in the transcript, the notes or the \
brand kit. Spell names exactly as the user's notes do. Apply change requests exactly and keep everything else."""


@dataclass
class EditorResult:
    storyboard: Storyboard
    from_ai: bool
    editor: str  # gemini | groq | claude | rules
    trace: list[str]
    motion: bool
    usage: dict = field(default_factory=dict)  # tokens the LLM editor used: calls, input, output


def _words_text(words: list[dict], a: int, b: int, limit: int = 80) -> str:
    return " ".join(w["text"] for w in words[a : b + 1])[:limit]


def initial_state(previous: dict | None, style: str, n_words: int, *, locked: bool, motion_allowed: bool,
                  motion_on: bool, max_cut: float = 0.6, video_type: str = "vlog") -> dict:
    state = fallback_storyboard(style, n_words, video_type).model_dump()
    state["music"] = get_recipe(video_type).music is not None
    if previous:
        state.update({k: v for k, v in previous.items() if k in state})
        state["remove_ranges"] = list(previous.get("remove_ranges") or [])
        state["emoji_moments"] = list(previous.get("emoji_moments") or [])
    if locked:
        state["style"] = style
    state.update({"_style_locked": locked, "_motion_allowed": motion_allowed, "_motion": motion_on,
                  "_max_cut": max_cut})
    return state


def to_storyboard(state: dict, n_words: int, duration: float) -> Storyboard:
    data = {k: v for k, v in state.items() if not k.startswith("_")}
    return validate_storyboard(Storyboard.model_validate(data), n_words, duration, state.get("_max_cut", 0.6))


_TARGET_RE = re.compile(
    r"(?:make it|keep it|cut it(?: down)? to|trim it to|shorten(?: it)? to|reduce(?: it)? to|under|at most|max(?:imum)?"
    r"|around|about|only|limit(?: it)? to|length(?: of)?|duration(?: of)?|in)\s*(?:a\s*)?(\d{1,3})\s*-?\s*"
    r"(?:s|sec|secs|second|seconds)\b"
    r"|\b(\d{1,3})\s*-?\s*(?:s|sec|secs|second|seconds)\s*(?:reel|video|clip|long|version|max|edit|cut)\b",
    re.IGNORECASE,
)


def parse_target(texts: list[str]) -> float | None:
    """'make it 40 sec', '30 second reel', 'under 60s' -> seconds. The last request wins."""
    target = None
    for text in texts:
        for m in _TARGET_RE.finditer(text or ""):
            value = int(m.group(1) or m.group(2))
            if 5 <= value <= 180:
                target = float(value)
    return target


def output_seconds(state: dict, words: list[dict], duration: float) -> float:
    sb = to_storyboard(state, len(words), duration)
    segments = keep_segments(words, duration, removed_word_set(sb), trim_start=sb.trim_start_s, trim_end=sb.trim_end_s)
    return output_duration(segments)


def units_for(words: list[dict], segments: list[dict] | None) -> list[dict]:
    """Editing units: Whisper segments (with quality scores) or, without them, punctuation sentences."""
    if segments:
        return [s for s in segments if 0 <= s["first_word"] <= s["last_word"] < len(words)]
    return [{"first_word": a, "last_word": b, "avg_logprob": 0.0, "compression_ratio": 1.0, "no_speech_prob": 0.0}
            for a, b in sentences(words)]


def unclear(unit: dict) -> bool:
    """Whisper's standard signals for hallucinated or unintelligible audio."""
    return unit.get("compression_ratio", 1) > 2.4 or (unit.get("avg_logprob", 0) < -1.0 and unit.get("no_speech_prob", 0) > 0.5)


def _unit_text(words: list[dict], u: dict) -> str:
    return " ".join(normalize_word(w["text"]) for w in words[u["first_word"] : u["last_word"] + 1])


def _unit_seconds(words: list[dict], u: dict) -> float:
    return words[u["last_word"]]["end"] - words[u["first_word"]]["start"]


def fit_to_target(state: dict, words: list[dict], units: list[dict], duration: float, target: float) -> list[str]:
    """Bring the edit to about `target` seconds. The opening (context/hook) and the closing are protected; the middle
    is trimmed, starting with repeated looped text (a Whisper hallucination sign), then the least clearly heard parts."""
    trace: list[str] = []
    out = output_seconds(state, words, duration)
    if out <= target + 2:
        return trace
    state["_max_cut"] = max(state.get("_max_cut", 0.6), 0.85)

    def live(u: dict) -> bool:
        removed = removed_word_set(to_storyboard(state, len(words), duration))
        return any(i not in removed for i in range(u["first_word"], u["last_word"] + 1))

    candidates = [u for u in units if live(u)]
    protected: set[int] = set()
    for budget, ordered in ((target * 0.4, candidates), (target * 0.25, list(reversed(candidates)))):
        used = 0.0
        for u in ordered:
            seconds = _unit_seconds(words, u)
            if used and used + seconds > budget:
                break
            protected.add(id(u))
            used += seconds
    repeats = Counter(_unit_text(words, u) for u in candidates)

    def priority(u: dict) -> tuple:
        looped = repeats[_unit_text(words, u)] > 1
        return (0 if looped else 1 if unclear(u) else 2, u.get("avg_logprob", 0))

    middle = sorted((u for u in candidates if id(u) not in protected), key=priority)
    for unit in middle:
        if out <= target + 2:
            break
        args = {"start_word": unit["first_word"], "end_word": unit["last_word"], "reason": f"shortened to {target:.0f}s"}
        result = apply_tool(state, "remove_words", args, words, duration)
        after = output_seconds(state, words, duration) if result.startswith("ok") else out
        if result.startswith("ok") and after < target - 6 and out - target < 8:
            state["remove_ranges"].pop()  # this cut would undershoot by a lot; skip it
            continue
        trace.append(_trace_line("remove_words", args, result))
        out = after
    trace.append(f"length check: {out:.1f}s for a {target:.0f}s target")
    return trace


def apply_tool(state: dict, name: str, args: dict, words: list[dict], duration: float) -> str:
    """Execute one editing tool against the working storyboard. Returns a short result; errors come back as text so
    the model can correct itself."""
    if args is not None and not isinstance(args, dict):
        return "error: arguments must be a JSON object"
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
        if already + (b - a + 1) > n * state.get("_max_cut", 0.6):
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
    if name == "set_look":
        done: list[str] = []
        if args.get("video_type"):
            video_type = str(args["video_type"]).lower()
            if video_type not in RECIPES:
                return f"error: unknown video_type; use one of {', '.join(VIDEO_TYPES)}"
            recipe = get_recipe(video_type)
            state["video_type"] = video_type
            if not state["_style_locked"]:
                state["style"] = recipe.style
            state["music"] = recipe.music is not None
            done.append(f"ok: {video_type}")
        for key, tool, tool_args in (
            ("style", "set_style", {"style": args.get("style")}),
            ("music", "set_music", {"enabled": args.get("music")}),
            ("framing", "set_framing", {"mode": args.get("framing")}),
            ("captions", "set_captions", {"enabled": args.get("captions") != "off",
                                          "position": args.get("captions") or state["caption_position"]}),
            ("motion", "set_motion_graphics", {"enabled": args.get("motion")}),
        ):
            if args.get(key) is not None:
                done.append(_apply_tool(state, tool, tool_args, words, duration))
        if not done:
            return "error: give at least one field"
        errors = [d for d in done if d.startswith("error")]
        summary = ", ".join(d.split(": ", 1)[-1] for d in done if d.startswith("ok"))
        return "; ".join(errors) + (f" (applied: {summary})" if summary else "") if errors else f"ok: {summary}"
    if name == "set_text":
        if "hook" in args:
            state["hook_text"] = " ".join(str(args.get("hook") or "").split()[:6])[:40]
        if "punchline" in args:
            state["punchline_text"] = " ".join(str(args.get("punchline") or "").split()[:7])[:48]
        if "cta" in args:
            state["cta_text"] = " ".join(str(args.get("cta") or "").split()[:8])[:48]
        return f'ok: hook "{state["hook_text"]}", end card "{state["punchline_text"]}" / "{state["cta_text"]}"'
    if name == "emphasize":
        notes: list[str] = []
        if args.get("words") is not None:
            notes.append(_apply_tool(state, "highlight_words", {"word_indices": args["words"]}, words, duration))
        if args.get("emoji") is not None:
            state["emoji_moments"] = []
            for item in args["emoji"][:4]:
                if isinstance(item, dict):
                    notes.append(_apply_tool(state, "add_emoji", {"word_index": item.get("word"),
                                                                  "emoji": item.get("emoji")}, words, duration))
        return "; ".join(notes) or "error: give words and/or emoji"
    if name == "preview_edit":
        sb = to_storyboard(state, n, duration)
        removed = removed_word_set(sb)
        segments = keep_segments(words, duration, removed, trim_start=sb.trim_start_s, trim_end=sb.trim_end_s)
        kept, last = [], -2
        for i, w in enumerate(words):
            if i not in removed and map_span(w["start"], w["end"], segments) is not None:
                kept.append(w["text"] if i == last + 1 else f"[{i}] {w['text']}")
                last = i
        preview = {"seconds": output_duration(segments), "of": round(duration, 1), "type": sb.video_type,
                   "style": sb.style, "music": sb.music, "hook": sb.hook_text, "end": sb.punchline_text}
        if state.get("_target"):
            preview["target"] = f"{state['_target'] - 3:.0f}-{state['_target'] + 2:.0f}"
        preview["kept"] = " ".join(kept)[:1200]
        return json.dumps(preview, ensure_ascii=False)
    if name == "ask_user":
        state["question_for_user"] = str(args.get("question", ""))[:200]
        return "ok: question will be sent with the preview"
    if name == "finish":
        state["edit_notes"] = [str(x)[:120] for x in (args.get("notes") or [])][:3]
        state["scene_description"] = str(args.get("scene", ""))[:400]
        if args.get("question"):
            state["question_for_user"] = str(args["question"])[:200]
        return "ok: finished"
    return f"error: unknown tool {name}"


def drop_orphans(state: dict, words: list[dict], duration: float) -> list[str]:
    """Remove short leftovers stranded between two cuts ("This a pure definition of"): they read as glitches."""
    removed = removed_word_set(to_storyboard(state, len(words), duration))
    trace, i = [], 0
    while i < len(words):
        if i in removed or i == 0 or (i - 1) not in removed:
            i += 1
            continue
        j = i
        while j + 1 < len(words) and j + 1 not in removed:
            j += 1
        if j + 1 < len(words):  # a kept run with cuts on both sides
            spoken = [w for w in words[i : j + 1] if normalize_word(w["text"]) not in FILLERS]
            if len(spoken) <= 4 and words[j]["end"] - words[i]["start"] < 1.6:
                args = {"start_word": i, "end_word": j, "reason": "stranded fragment"}
                result = apply_tool(state, "remove_words", args, words, duration)
                if result.startswith("ok"):
                    trace.append(_trace_line("remove_words", args, result))
        i = j + 1
    return trace


def _trace_line(name: str, args: dict | None, result: str) -> str:
    shown = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in (args or {}).items())[:160]
    return f"{'✗ ' if result.startswith('error') else ''}{name}({shown})"


# ------------------------------------------------------------------ rule-based fallback (no LLM)

_TYPE_ASK_RE = re.compile(r"\b(?:make it|more|less|vibe|feel|mood|tone|turn it into|it's an?|this is an?)\b(.{0,40})")
_STYLE_RE = re.compile(r"\b(" + "|".join(STYLE_ORDER) + r")\b")
_PHRASE_RE = re.compile(
    r"(?:cut|remove|delete|drop)(?: out)?(?: the)?(?: part| bit| section| line)?(?: where| when)? "
    r"(?:i|we|he|she|they) (?:say|said|says|mention|mentioned|talk about)s? [\"“']?(.+?)[\"”']?\s*$"
)


RESTART_MARKERS = ("let me start again", "let me start over", "start again", "start over", "let me try again",
                   "one more time", "take two", "scratch that", "let me redo", "wait wait")


def sentences(words: list[dict]) -> list[tuple[int, int]]:
    """Sentence spans by punctuation. Unpunctuated speech (common in Urdu/Hindi transcripts) splits on pauses and
    every 15 words instead, so it never becomes one giant sentence."""
    punctuated = sum(w["text"].endswith((".", "!", "?")) for w in words) >= len(words) / 40
    spans, start = [], 0
    for i, w in enumerate(words):
        last = i == len(words) - 1
        if punctuated:
            end = w["text"].endswith((".", "!", "?"))
        else:
            end = i - start + 1 >= 15 or (not last and words[i + 1]["start"] - w["end"] >= 0.6)
        if end or last:
            spans.append((start, i))
            start = i + 1
    return spans


def auto_rules(state: dict, words: list[dict], duration: float, units: list[dict] | None = None) -> list[str]:
    """No-LLM editing pass: drop unclear/hallucinated audio and restart sentences, like an editor would."""
    trace: list[str] = []
    repeats = Counter(_unit_text(words, u) for u in units or [])
    for unit in units or []:
        looped = repeats[_unit_text(words, unit)] >= 3 and len(_unit_text(words, unit).split()) <= 6
        if unclear(unit) or looped:
            reason = "unclear audio" if unclear(unit) else "repeated loop"
            args = {"start_word": unit["first_word"], "end_word": unit["last_word"], "reason": reason}
            trace.append(_trace_line("remove_words", args, apply_tool(state, "remove_words", args, words, duration)))
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


GREETING_RE = re.compile(r"^(hi|hey|hello|hello everyone|assalam|salam|what'?s up|welcome|so|okay|ok)\b", re.I)


def auto_text(state: dict, words: list[dict], brand: dict, english: bool = True) -> list[str]:
    """No-LLM hook and end card, so the video type's title and end-card graphics still show: the first short kept
    sentence that is not a greeting becomes the hook (English speech only: on-screen text is English), the brand's call
    to action becomes the end card."""
    removed = {i for r in state["remove_ranges"] for i in range(r["start_word"], r["end_word"] + 1)}
    args: dict = {}
    for a, b in sentences(words)[:4] if english else []:
        text = " ".join(w["text"] for w in words[a : b + 1]).strip(" .,!?")
        short = 2 <= b - a + 1 <= 6 and len(text) <= 40
        if short and not removed & set(range(a, b + 1)) and not GREETING_RE.match(text):
            args["hook"] = text
            break
    if brand.get("cta"):
        args["punchline"] = brand["cta"]
    return [_trace_line("set_text", args, apply_tool(state, "set_text", args, words, 0))] if args else []


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
        if (m := _TYPE_ASK_RE.search(t)) and (video_type := type_from_request(m.group(1))):
            run("set_look", video_type=video_type)
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
            previous, target=None, language=None, units=None, guess=None) -> str:
    duration = float(probe["duration"])
    orientation = "landscape" if probe["width"] > probe["height"] else "vertical"
    clip = (f"Clip: {duration:.1f}s {probe['width']}x{probe['height']} {orientation}, "
            f"{'audio' if probe['has_audio'] else 'no audio'}, speech: {language or 'unknown'}")
    if language and language != "en":
        clip += " (captions are shown in English: write all text in English)"
    clip += f", face: {f'one steady face at x={face_x:.2f}' if face_x is not None else 'no steady face'}."
    lines = [clip]
    kit = {k: v for k, v in (brand or {}).items() if v and k not in ("accent_color", "default_style")}
    if kit:
        lines.append(f"Brand kit: {json.dumps(kit, ensure_ascii=False)}")
    if user_context:
        lines.append(f"User's notes: {user_context}")
    if style_request:
        lines.append(f"Style: the user chose {style_request}; keep it.")
    if motion_allowed:
        lines.append("Motion graphics: the user asked for them.")
    if guess and not previous:
        lines.append(f"Keyword guess for video_type: {guess} (decide yourself).")
    if target:
        lines.append(f"Target length: about {target:.0f}s (the user asked). Keep the opening, the main point and the "
                     f"close; cut the weakest parts until preview seconds is {target - 3:.0f}-{target + 2:.0f}.")
    if previous:
        keep = {k: previous.get(k) for k in ("video_type", "style", "hook_text", "punchline_text", "cta_text",
                                            "remove_ranges", "highlight_word_indices", "emoji_moments", "crop_mode",
                                            "captions_enabled", "caption_position", "music", "trim_start_s",
                                            "trim_end_s") if previous.get(k) not in (None, "", [])}
        if keep.get("remove_ranges"):  # [start, end] pairs: the reasons only cost tokens here
            keep["remove_ranges"] = [[r["start_word"], r["end_word"]] for r in keep["remove_ranges"]]
        lines.append(f"Current edit (change only what is asked): {json.dumps(keep, ensure_ascii=False)}")
    if change_requests:
        lines.append("Change requests, oldest first: " + json.dumps(change_requests, ensure_ascii=False))
    lines.append("Transcript, one line per phrase: [start seconds] then word index and word; ? marks unclear audio.")
    lines.append(transcript_lines(words, units or units_for(words, None)) or "(no speech detected)")
    return "\n".join(lines)


def transcript_lines(words: list[dict], units: list[dict]) -> str:
    """Compact numbered transcript: about 2.5 tokens a word instead of ~10 for "i:word@seconds"."""
    starts = {u["first_word"]: u for u in units}
    lines: list[str] = []
    for i, w in enumerate(words):
        if i in starts or not lines:
            unit = starts.get(i)
            lines.append(f"[{w['start']:.1f}{'?' if unit and unclear(unit) else ''}]")
        lines[-1] += f" {i} {w['text']}"
    return "\n".join(lines)


def _echo(message: dict) -> dict:
    """Assistant message as it must be sent back (keeps provider extras such as Gemini thought signatures, drops the
    reasoning text, which would otherwise be re-sent and paid for on every later turn)."""
    out = {k: v for k, v in message.items() if not k.startswith("_") and k not in ("reasoning", "reasoning_content")}
    out["role"] = "assistant"
    if out.get("content") is None and not out.get("tool_calls"):
        out["content"] = ""
    return out


async def _agent(provider: llm.Provider, state: dict, frames: list[Path], prompt: str, words: list[dict],
                 duration: float, usage: dict | None = None) -> list[str]:
    usage = usage if usage is not None else {}
    content: list[dict] = [{"type": "text", "text": prompt}]
    if provider.max_images:
        content += [llm.image_part(f) for f in _spread(frames, provider.max_images)]
    elif provider.vision_model and frames:
        visual = await llm.describe_frames(provider, frames, usage)
        if visual:
            content[0]["text"] += f"\n\nWhat the frames show: {visual}"
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]
    trace: list[str] = []
    for _ in range(MAX_STEPS):
        reply = await llm.chat(provider, messages, tools=TOOLS, max_tokens=4000)
        llm.add_usage(usage, reply)
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


def _spread(frames: list[Path], count: int) -> list[Path]:
    """`count` frames spread over the clip (the first few would all show the opening)."""
    if len(frames) <= count:
        return frames
    return [frames[round(i * (len(frames) - 1) / max(count - 1, 1))] for i in range(count)]


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
    target_seconds: float | None = None,
    segments: list[dict] | None = None,
    language: str | None = None,
) -> EditorResult:
    duration = float(probe["duration"])
    guess = (previous or {}).get("video_type") or classify(words, user_context, brand)
    brand_style = brand.get("default_style") if brand.get("default_style") not in (None, "", "clean") else None
    style = style_request or (previous or {}).get("style") or brand_style or get_recipe(guess).style
    motion_allowed = motion_requested or any(MOTION_RE.search(n) for n in change_requests)
    motion_on = motion_requested or bool((previous or {}).get("motion"))
    target = target_seconds or parse_target([user_context or "", *change_requests])
    if target and target >= duration - 1:
        target = None  # already short enough
    units = units_for(words, segments)

    def fresh(base: dict | None = None) -> dict:
        state = initial_state(base if base is not None else previous, style, len(words), locked=bool(style_request),
                              motion_allowed=motion_allowed, motion_on=motion_on, max_cut=0.85 if target else 0.6,
                              video_type=guess)
        state["_target"] = target
        return state

    def finish(state: dict, from_ai: bool, editor: str, trace: list[str], usage: dict | None = None) -> EditorResult:
        trace = trace + drop_orphans(state, words, duration)
        if target:  # safety net: whoever edited, the result honours the requested length
            trace = trace + fit_to_target(state, words, units, duration, target)
        if usage and (usage.get("input") or usage.get("output")):
            trace.append(f"tokens: {usage['input']} in + {usage['output']} out over {usage['calls']} calls")
            log.info("editor %s used %s", editor, usage)
        return EditorResult(to_storyboard(state, len(words), duration), from_ai, editor, trace, state["_motion"],
                            usage or {})

    prompt = _prompt(words=words, probe=probe, face_x=face_x, brand=brand, user_context=user_context,
                     style_request=style_request, motion_allowed=motion_allowed, change_requests=change_requests,
                     previous=previous, target=target, language=language, units=units, guess=guess)
    for provider in llm.chain():
        usage: dict = {}
        if provider is None:  # Claude: the whole storyboard in one structured call
            from app.pipeline.director import direct

            if sb := await direct(frames=_spread(frames, 4), prompt=prompt, usage=usage):
                return finish(fresh(sb.model_dump()), True, "claude",
                              [f"storyboard planned in one structured call (video type: {sb.video_type})"], usage)
            continue
        state = fresh()
        try:
            trace = await _agent(provider, state, frames, prompt, words, duration, usage)
            return finish(state, True, provider.name, trace, usage)
        except (llm.LLMError, ValidationError, ValueError) as exc:
            log.warning("editor agent via %s (%s) failed: %s", provider.name, provider.model, str(exc)[:300])

    state = fresh()
    trace = [] if previous else auto_rules(state, words, duration, units) + auto_text(
        state, words, brand, english=(language or "en").startswith("en"))
    if not previous:
        trace.append(f"video type: {guess} (keywords)")
    trace += apply_rules(state, change_requests[-1:] if previous else change_requests, words, duration)
    return finish(state, False, "rules", trace)
