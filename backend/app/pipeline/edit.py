"""Full edit: probe -> transcribe -> face focus -> director -> cuts -> captions -> render."""

import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.config import settings
from app.integrations import llm
from app.pipeline.cuts import keep_segments, output_duration
from app.pipeline.editor_agent import run_editor
from app.pipeline.faces import face_center
from app.pipeline.frames import sample_frames
from app.pipeline.probe import ProbeInfo, probe as probe_file
from app.pipeline.render_ffmpeg import RenderPlan, choose_reframe, finalize, render
from app.pipeline.render_hyperframes import build_data, hyperframes_available, render_motion
from app.pipeline.storyboard import Storyboard, removed_word_set
from app.pipeline.styles import StylePreset, get_preset
from app.pipeline.subtitles import build_ass
from app.pipeline.transcribe import transcribe

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


def find_music(style: str) -> Path | None:
    """Music bed for the style (assets/music/<style>.mp3). Calm styles have none on purpose."""
    music_dir = Path(settings.assets_dir) / "music"
    for candidate in sorted(music_dir.glob(f"{style}.*")) if music_dir.is_dir() else []:
        if candidate.suffix.lower() in {".mp3", ".m4a", ".wav", ".ogg"}:
            return candidate
    return None


def make_summary(
    duration_in: float,
    duration_out: float,
    sb: Storyboard,
    reframe: str,
    preset: StylePreset,
    has_audio: bool,
    captions: bool,
    music_used: bool,
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
    if music_used:
        bullets.append("Soft music bed under your voice")
    bullets.append(f"Style: {preset.label} ({preset.description})")
    bullets += sb.edit_notes[:2]
    return bullets


async def run_edit(inp: EditInput) -> EditOutput:
    inp.workdir.mkdir(parents=True, exist_ok=True)
    probe = ProbeInfo.from_dict(inp.probe) if inp.probe else await probe_file(str(inp.src))
    transcript = inp.transcript if inp.transcript is not None else await transcribe(str(inp.src))
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
    )
    sb, from_ai = editor.storyboard, editor.from_ai
    want_motion = inp.motion or editor.motion

    removed = removed_word_set(sb)
    segments = keep_segments(words, probe.duration, removed, trim_start=sb.trim_start_s, trim_end=sb.trim_end_s)
    out_duration = output_duration(segments)
    preset = get_preset(sb.style)
    reframe = choose_reframe(probe, sb.crop_mode, face_x)
    accent = inp.brand.get("accent_color")
    accent = accent if accent and accent.upper() != DEFAULT_ACCENT else None

    ass_text = build_ass(
        words=words,
        segments=segments,
        removed=removed,
        preset=preset,
        out_duration=out_duration,
        captions=sb.captions_enabled,
        caption_position=sb.caption_position,
        hook_text=sb.hook_text,
        punchline_text=sb.punchline_text,
        cta_text=sb.cta_text,
        highlight_indices=set(sb.highlight_word_indices),
        accent=accent,
    )
    ass_file = None
    if ass_text:
        ass_file = inp.workdir / "captions.ass"
        ass_file.write_text(ass_text, encoding="utf-8")

    music = find_music(sb.style) if sb.music else None
    plan = RenderPlan(
        segments=segments,
        preset=preset,
        reframe=reframe,
        focus_x=face_x,
        ass_file=ass_file,
        music_file=music,
        out_duration=out_duration,
    )
    fonts = Path(settings.assets_dir) / "fonts"
    used_motion = False
    if want_motion and hyperframes_available():
        try:
            base = await render(inp.src, probe, replace(plan, ass_file=None), inp.workdir, fonts, out_name="base.mp4")
            data = build_data(
                words=words, segments=segments, removed=removed, preset=preset,
                out_duration=out_duration, storyboard=sb.model_dump(), accent=accent,
            )
            master = await render_motion(base, data, inp.workdir)
            used_motion = True
        except Exception as exc:
            log.warning("motion render failed, using the standard edit: %s", exc)
    if not used_motion:
        master = await render(inp.src, probe, plan, inp.workdir, fonts)
    outputs = await finalize(master, out_duration, inp.workdir)

    summary = make_summary(
        probe.duration, out_duration, sb, reframe, preset, probe.has_audio, bool(sb.captions_enabled and words), music is not None
    )
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
