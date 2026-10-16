"""brag-style motion layer: fill the vetted HyperFrames template with storyboard data, render, then add the audio back.

The model only ever produces JSON (the Storyboard). This module turns it into data for a fixed template, so no
model-written HTML or JavaScript is executed in the headless browser.
"""

import json
import shutil
from pathlib import Path

from app.config import settings
from app.pipeline.cuts import Segment
from app.pipeline.proc import run
from app.pipeline.styles import StylePreset
from app.pipeline.subtitles import _case, group_lines, map_words

CAPTION_Y = {"lower": 1300, "middle": 860, "upper": 430}
ZOOM_STYLES = {"hype", "funny", "clean"}


def _safe_emoji(value: str) -> str | None:
    value = value.strip()
    if not value or len(value) > 6 or any(ch.isascii() for ch in value):
        return None
    return value


def hyperframes_available() -> bool:
    cli = settings.hyperframes_cli
    return bool(cli) and Path(cli).is_file()


def build_data(
    *,
    words: list[dict],
    segments: list[Segment],
    removed: set[int],
    preset: StylePreset,
    out_duration: float,
    storyboard: dict,
    accent: str | None,
) -> dict:
    mapped = map_words(words, segments, removed) if storyboard.get("captions_enabled", True) else []
    highlights = set(storyboard.get("highlight_word_indices") or [])
    punch = storyboard.get("punchline_text") or ""
    punch_start = max(0.0, out_duration - 2.2) if punch and out_duration > 4 else out_duration

    lines = group_lines(mapped, preset.words_per_line)
    out_lines = []
    for j, line in enumerate(lines):
        next_start = lines[j + 1][0]["start"] if j + 1 < len(lines) else out_duration
        start, end = line[0]["start"], min(line[-1]["end"] + 0.15, next_start, punch_start)
        if start >= punch_start or end - start < 0.05:
            continue
        out_lines.append({
            "start": start,
            "end": end,
            "words": [{"t": _case(w["text"], preset), "s": w["start"], "e": w["end"], "hl": w["i"] in highlights}
                      for w in line],
        })

    zooms: list[float] = []
    if preset.name in ZOOM_STYLES:
        for m in mapped:
            if m["i"] in highlights and m["start"] < punch_start - 0.6 and (not zooms or m["start"] - zooms[-1] > 1.4):
                zooms.append(m["start"])

    by_index = {m["i"]: m for m in mapped}
    emojis = []
    for moment in (storyboard.get("emoji_moments") or [])[:4]:
        emoji = _safe_emoji(moment.get("emoji", ""))
        word = by_index.get(moment.get("word_index"))
        if emoji and word and word["start"] < punch_start - 1:
            emojis.append({"t": word["start"], "e": emoji})

    return {
        "duration": round(out_duration, 3),
        "style": {
            "fs": preset.font_size,
            "primary": preset.primary,
            "accent": accent or preset.highlight,
            "pop": preset.pop or preset.name in ZOOM_STYLES,
            "progress": preset.progress_bar,
        },
        "caption_y": CAPTION_Y.get(storyboard.get("caption_position") or "lower", 1300),
        "lines": out_lines,
        "zooms": zooms,
        "emojis": emojis,
        "hook": _case(storyboard.get("hook_text") or "", preset),
        "punch": _case(punch, preset),
        "cta": storyboard.get("cta_text") or "",
        "punch_start": round(punch_start, 3),
    }


async def render_motion(base: Path, data: dict, workdir: Path) -> Path:
    """Renders the composition over `base` (video + audio). Returns the muxed master path."""
    assets = Path(settings.assets_dir)
    comp = workdir / "hf"
    if comp.exists():
        shutil.rmtree(comp)
    (comp / "fonts").mkdir(parents=True)
    shutil.copy(base, comp / "base.mp4")
    shutil.copy(assets / "hyperframes" / "gsap.min.js", comp / "gsap.min.js")
    for font in (assets / "fonts").glob("*.ttf"):
        shutil.copy(font, comp / "fonts" / font.name)
    template = (assets / "hyperframes" / "reel.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace("__DURATION__", f"{data['duration']:.3f}").replace("/*__DATA__*/ null", payload)
    (comp / "index.html").write_text(html, encoding="utf-8")

    video_only = workdir / "motion.mp4"
    await run(
        ["node", settings.hyperframes_cli, "render", str(comp), "-o", str(video_only), "--fps", "30",
         "--crf", "20", "--workers", str(settings.hyperframes_workers), "--quiet"],
        timeout=300 + data["duration"] * 20,
    )
    master = workdir / "master.mp4"
    await run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video_only), "-i", str(base), "-map", "0:v:0", "-map", "1:a:0?",
         "-c:v", "copy", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(master)],
        timeout=120,
    )
    return master
