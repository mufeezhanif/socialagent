"""Full edit: probe -> transcribe -> face focus -> director -> cuts -> captions -> render."""

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.config import settings
from app.integrations import llm
from app.pipeline.cuts import keep_segments, output_duration
from app.pipeline.editor_agent import run_editor
from app.pipeline.faces import face_center
from app.pipeline.genres import LOOK_SUMMARY, MUSIC_LABEL, Recipe, cut_points, find_track, get_recipe, plan_sfx, sfx_file
from app.pipeline.frames import sample_frames
from app.pipeline.probe import ProbeInfo, probe as probe_file
from app.pipeline.render_ffmpeg import RenderPlan, choose_reframe, finalize, render
from app.pipeline.render_hyperframes import build_data, hyperframes_available, render_motion
from app.pipeline.storyboard import Storyboard, removed_word_set
from app.pipeline.styles import StylePreset, get_preset
from app.pipeline.subtitles import build_ass, map_words
from app.pipeline.transcribe import transcribe, translate

log = logging.getLogger(__name__)
DEFAULT_ACCENT = "#FFD400"


@dataclass
class EditInput:
    src: Path
    workdir: Path
    style_request: str | None = None
    user_context: str | None = None
    brand: dict = field(default_factory=dict)
    change_requests: list[str] = field(default_factory=list)
    previous_storyboard: dict | None = None
    probe: dict | None = None
    transcript: dict | None = None
    face_x: float | None = None
    face_checked: bool = False
    motion: bool = False  # brag-style HyperFrames motion layer (slower, opt-in)
    target_seconds: float | None = None  # requested reel length; also parsed from the user's notes


@dataclass
class EditOutput:
    master: Path
    preview: Path
    cover: Path
    probe: dict
    transcript: dict
    face_x: float | None
    storyboard: dict
    from_ai: bool
    duration_in: float
    duration_out: float
    summary: list[str]
    question: str
    motion: bool = False
    editor: str = "rules"
    trace: list[str] = field(default_factory=list)


def vocabulary_hint(user_context: str | None, brand: dict) -> str | None:
    """Names and terms the speaker is likely to say, from the user's note and brand kit (length requests removed)."""
    from app.pipeline.editor_agent import _TARGET_RE

    parts = [_TARGET_RE.sub("", user_context or "").strip(" .,-"), brand.get("niche") or ""]
    hint = ". ".join(p for p in parts if p)
    return hint[:400] or None


def find_music(style: str) -> Path | None:
    """Music bed for the style (assets/music/<style>.mp3)."""
    return find_track(style)


def pick_music(recipe: Recipe, style: str) -> Path | None:
    """The video type's track (emotional piano for a heartfelt clip), unless the user chose a different style."""
    if style != recipe.style:
        return find_music(style) or find_track(recipe.music)
    return find_track(recipe.music) or find_music(style)


def plan_sounds(recipe: Recipe, sb: Storyboard, words: list[dict], segments: list, removed: set[int],
                highlight_times: list[float], out_duration: float, emojis: bool) -> list[tuple[float, Path, float]]:
    """Sound effects for the recipe on the edited timeline, as (seconds, file, volume)."""
    emoji_times: list[float] = []
    if emojis:
        placed = {w["i"]: w["start"] for w in map_words(words, segments, removed)}
        emoji_times = [placed[m.word_index] for m in sb.emoji_moments if m.word_index in placed]
    punch_start = out_duration - 2.2 if sb.punchline_text and out_duration > 4 else None
    events = plan_sfx(recipe, cuts=cut_points(segments, out_duration), highlights=highlight_times, emojis=emoji_times,
                      out_duration=out_duration, hook=bool(sb.hook_text), punch_start=punch_start)
    return [(t, path, volume) for t, name, volume in events if (path := sfx_file(name))]


def make_summary(
    duration_in: float,
    duration_out: float,
    sb: Storyboard,
    reframe: str,
    preset: StylePreset,
    has_audio: bool,
    captions: bool,
    music_used: bool,
    recipe: Recipe | None = None,
    music_name: str = "",
) -> list[str]:
    bullets: list[str] = []
    cut = duration_in - duration_out
    if cut >= 0.5:
        bullets.append(f"Cut {cut:.0f}s of pauses and filler")
    for r in sb.remove_ranges[:2]:
        bullets.append(f"Removed: {r.reason}")
    bullets.append(
        {"crop": "Vertical 9:16, framed on you", "blur_pad": "Vertical 9:16 with a blurred backdrop"}.get(
            reframe, "Vertical 9:16"
        )
    )
    if captions:
        bullets.append("Word-by-word captions" + (f' + hook "{sb.hook_text}"' if sb.hook_text else ""))
    elif sb.hook_text:
        bullets.append(f'Hook: "{sb.hook_text}"')
    if sb.punchline_text:
        bullets.append(f'End card: "{sb.punchline_text}"')
    if has_audio:
        bullets.append("Cleaned and levelled audio")
    if recipe:
        bullets.append(f"Edited as {'an' if recipe.name[0] in 'aeiou' else 'a'} {recipe.name} video: "
                       f"{LOOK_SUMMARY.get(recipe.name, 'clean look')}")
    if music_used:
        bullets.append(f"{MUSIC_LABEL.get(music_name, 'Soft')} music bed under your voice")
    bullets.append(f"Style: {preset.label} ({preset.description})")
    bullets += sb.edit_notes[:2]
    return bullets


async def run_edit(inp: EditInput) -> EditOutput:
    inp.workdir.mkdir(parents=True, exist_ok=True)
    probe = ProbeInfo.from_dict(inp.probe) if inp.probe else await probe_file(str(inp.src))
    vocab = vocabulary_hint(inp.user_context, inp.brand)
    transcript = inp.transcript if inp.transcript is not None else await transcribe(str(inp.src), vocab)
    words = transcript.get("words", [])
    face_x = inp.face_x if inp.face_checked else await face_center(str(inp.src), probe.duration)

    frames = await sample_frames(str(inp.src), probe.duration, inp.workdir / "frames") if llm.any_configured() else []
    editor = await run_editor(
        frames=frames,
        words=words,
        probe=probe.to_dict(),
        face_x=face_x,
        style_request=inp.style_request,
        user_context=inp.user_context,
        brand=inp.brand,
        change_requests=inp.change_requests,
        previous=inp.previous_storyboard,
        motion_requested=inp.motion,
        target_seconds=inp.target_seconds,
        segments=transcript.get("segments"),
        language=transcript.get("language"),
    )
    sb, from_ai = editor.storyboard, editor.from_ai
    want_motion = inp.motion or editor.motion

    removed = removed_word_set(sb)
    segments = keep_segments(words, probe.duration, removed, trim_start=sb.trim_start_s, trim_end=sb.trim_end_s)
    out_duration = output_duration(segments)
    preset = get_preset(sb.style)
    recipe = get_recipe(sb.video_type)
    cuts = cut_points(segments, out_duration)
    reframe = choose_reframe(probe, sb.crop_mode, face_x)
    accent = inp.brand.get("accent_color")
    accent = accent if accent and accent.upper() != DEFAULT_ACCENT else None

    # Captions: the spoken words, or English translations (timed on the same source timeline) for other languages.
    caption_words, caption_removed, caption_hl = words, removed, set(sb.highlight_word_indices)
    language = transcript.get("language")
    if sb.captions_enabled and words and language and language != "en" and settings.caption_language == "en":
        if "translation" not in transcript:
            transcript["translation"] = await translate(str(inp.src), vocab)
        english = (transcript.get("translation") or {}).get("words") or []
        if english:
            spans = [(words[i]["start"], words[i]["end"]) for i in sb.highlight_word_indices if i < len(words)]
            caption_words, caption_removed = english, set()  # cut parts drop out by timing
            caption_hl = {j for j, w in enumerate(english) if any(w["start"] < e and w["end"] > s for s, e in spans)}

    ass_text = build_ass(
        words=caption_words,
        segments=segments,
        removed=caption_removed,
        preset=preset,
        out_duration=out_duration,
        captions=sb.captions_enabled,
        caption_position=sb.caption_position,
        hook_text=sb.hook_text,
        punchline_text=sb.punchline_text,
        cta_text=sb.cta_text,
        highlight_indices=caption_hl,
        accent=accent,
        recipe=recipe,
        flash_times=cuts,
        handle=inp.brand.get("handle") or "",
    )
    ass_file = None
    if ass_text:
        ass_file = inp.workdir / "captions.ass"
        ass_file.write_text(ass_text, encoding="utf-8")

    music = pick_music(recipe, sb.style) if sb.music else None
    highlight_times = [w["start"] for w in map_words(caption_words, segments, caption_removed) if w["i"] in caption_hl]
    sfx = plan_sounds(recipe, sb, words, segments, removed, highlight_times, out_duration, emojis=False)
    plan = RenderPlan(
        segments=segments,
        preset=preset,
        reframe=reframe,
        focus_x=face_x,
        ass_file=ass_file,
        music_file=music,
        out_duration=out_duration,
        music_volume=recipe.music_volume,
        sfx=sfx,
        letterbox=recipe.letterbox,
        grain=recipe.grain,
        fades=recipe.fades,
        drift=recipe.drift,
    )
    fonts = Path(settings.assets_dir) / "fonts"
    used_motion = False
    if want_motion and hyperframes_available():
        try:
            motion_sfx = plan_sounds(recipe, sb, words, segments, removed, highlight_times, out_duration,
                                     emojis=caption_words is words)  # emoji pops are drawn by the motion layer
            base = await render(inp.src, probe, replace(plan, ass_file=None, sfx=motion_sfx), inp.workdir, fonts,
                                out_name="base.mp4")
            motion_sb = {**sb.model_dump(), "highlight_word_indices": sorted(caption_hl), "emoji_moments": []
                         if caption_words is not words else sb.model_dump()["emoji_moments"]}
            data = build_data(
                words=caption_words, segments=segments, removed=caption_removed, preset=preset,
                out_duration=out_duration, storyboard=motion_sb, accent=accent,
            )
            master = await render_motion(base, data, inp.workdir)
            used_motion = True
        except Exception as exc:
            log.warning("motion render failed, using the standard edit: %s", exc)
    if not used_motion:
        master = await render(inp.src, probe, plan, inp.workdir, fonts)
    outputs = await finalize(master, out_duration, inp.workdir)

    summary = make_summary(
        probe.duration, out_duration, sb, reframe, preset, probe.has_audio, bool(sb.captions_enabled and words),
        music is not None, recipe, music.stem if music else "",
    )
    if caption_words is not words:
        summary.insert(-1, f"English captions (translated from {language})")
    if used_motion:
        summary.insert(-1, "Motion graphics: kinetic captions, zoom punches, emoji pops, end card")
    elif want_motion:
        summary.append("Motion graphics aren't available right now, so this is the standard edit")
    return EditOutput(
        master=outputs["master"],
        preview=outputs["preview"],
        cover=outputs["cover"],
        probe=probe.to_dict(),
        transcript=transcript,
        face_x=face_x,
        storyboard=sb.model_dump(),
        from_ai=from_ai,
        duration_in=probe.duration,
        duration_out=out_duration,
        summary=summary,
        question=sb.question_for_user,
        motion=used_motion,
        editor=editor.editor,
        trace=editor.trace,
    )
