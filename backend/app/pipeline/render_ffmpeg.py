"""One FFmpeg pass: cut + zoom alternation + 9:16 reframe + grade + look (drift, grain, letterbox, fades) + captions
+ cleaned/levelled audio (+ music bed and sound effects)."""

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline.cuts import Segment
from app.pipeline.genres import LETTERBOX_PX
from app.pipeline.probe import ProbeInfo
from app.pipeline.proc import run
from app.pipeline.styles import StylePreset

OUT_W, OUT_H = 1080, 1920
PREVIEW_MAX_MB = 14.5


@dataclass
class RenderPlan:
    segments: list[Segment]
    preset: StylePreset
    reframe: str  # fill | crop | blur_pad
    focus_x: float | None
    ass_file: Path | None
    music_file: Path | None
    out_duration: float
    music_volume: float = 0.22
    sfx: list[tuple[float, Path, float]] = field(default_factory=list)  # (output seconds, file, volume)
    letterbox: bool = False
    grain: bool = False
    fades: bool = False
    drift: bool = False  # slow handheld-style float


def _even(value: float) -> int:
    return max(2, int(value) // 2 * 2)


def choose_reframe(probe: ProbeInfo, crop_mode: str, focus_x: float | None) -> str:
    ratio = probe.width / max(probe.height, 1)
    if ratio <= 0.8:
        return "fill"  # already vertical-ish: scale and trim the edges
    if crop_mode == "crop" or (crop_mode == "auto" and focus_x is not None):
        return "crop"
    return "blur_pad"


def look_filters(plan: RenderPlan) -> list[str]:
    """Video filters after the reframe, in order: drift, grade, grain, letterbox (captions go on top later)."""
    out: list[str] = []
    if plan.drift:
        out.append(f"scale={_even(OUT_W * 1.08)}:{_even(OUT_H * 1.08)},"
                   f"crop={OUT_W}:{OUT_H}:x='(iw-ow)/2*(1+0.8*sin(2*PI*t/11))':y='(ih-oh)/2*(1+0.8*cos(2*PI*t/13))'")
    if plan.preset.grade:
        out.append(plan.preset.grade)
    if plan.grain:
        out.append("noise=c0s=7:c0f=t+u")  # luma-only uniform grain: far cheaper than colour noise
    if plan.letterbox:
        bar = LETTERBOX_PX
        out.append(f"drawbox=x=0:y=0:w=iw:h={bar}:color=black:t=fill,drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black:t=fill")
    return out


def _fade_filters(plan: RenderPlan, audio: bool) -> str:
    if not plan.fades or plan.out_duration < 3:
        return ""
    end = plan.out_duration
    if audio:
        return f",afade=t=in:d=0.3,afade=t=out:st={end - 0.7:.3f}:d=0.7"
    return f",fade=t=in:st=0:d=0.4,fade=t=out:st={end - 0.6:.3f}:d=0.6"


def build_filtergraph(probe: ProbeInfo, plan: RenderPlan, music_input: int | None, silence_input: int | None,
                      sfx_inputs: list[int] | None = None) -> str:
    n = len(plan.segments)
    W, H = _even(probe.width), _even(probe.height)
    fx = plan.focus_x if plan.focus_x is not None else 0.5
    parts: list[str] = []

    parts.append(f"[0:v]split={n}" + "".join(f"[s{i}]" for i in range(n)) if n > 1 else "[0:v]null[s0]")
    if probe.has_audio:
        parts.append(f"[0:a]asplit={n}" + "".join(f"[t{i}]" for i in range(n)) if n > 1 else "[0:a]anull[t0]")

    concat_in = ""
    for i, (s, e) in enumerate(plan.segments):
        chain = f"[s{i}]trim=start={s}:end={e},setpts=PTS-STARTPTS"
        if plan.preset.zoom_alternate and i % 2 == 1:
            chain += f",crop=w=trunc(iw/1.1/2)*2:h=trunc(ih/1.1/2)*2:x=(iw-ow)*{fx:.3f}:y=(ih-oh)/2"
        chain += f",scale={W}:{H},setsar=1[v{i}]"
        parts.append(chain)
        concat_in += f"[v{i}]"
        if probe.has_audio:
            parts.append(f"[t{i}]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a{i}]")
            concat_in += f"[a{i}]"
    if probe.has_audio:
        parts.append(f"{concat_in}concat=n={n}:v=1:a=1[vc][ac]")
    else:
        parts.append(f"{concat_in}concat=n={n}:v=1:a=0[vc]")

    if plan.reframe == "fill":
        parts.append(f"[vc]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H}[vr]")
    elif plan.reframe == "crop":
        if W / H > 9 / 16:
            parts.append(f"[vc]crop=w=trunc(ih*9/32)*2:h=ih:x=(iw-ow)*{fx:.3f}:y=0,scale={OUT_W}:{OUT_H}[vr]")
        else:
            parts.append(f"[vc]crop=w=iw:h=trunc(iw*16/18)*2:x=0:y=(ih-oh)/2,scale={OUT_W}:{OUT_H}[vr]")
    else:
        parts.append(
            "[vc]split[bga][fga];"
            "[bga]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:2,"
            f"scale={OUT_W}:{OUT_H},eq=brightness=-0.08:saturation=0.9[bg];"
            f"[fga]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[vr]"
        )

    post = look_filters(plan)
    if plan.ass_file:
        post.append(f"ass={plan.ass_file.name}:fontsdir=fonts")
    post += ["fps=30", "format=yuv420p"]
    parts.append("[vr]" + ",".join(post) + _fade_filters(plan, audio=False) + "[vout]")

    total = plan.out_duration
    loudnorm = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000"
    if probe.has_audio:
        parts.append("[ac]highpass=f=80,afftdn=nf=-25,acompressor=threshold=0.125:ratio=3:attack=5:release=150:makeup=2[voice]")
        base = "voice"
        if music_input is not None:
            parts.append(
                "[voice]asplit[vmix][vkey];"
                f"[{music_input}:a]aresample=48000,volume={plan.music_volume:.3f}[mus];"
                "[mus][vkey]sidechaincompress=threshold=0.04:ratio=10:attack=15:release=350[duck];"
                "[vmix][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]"
            )
            base = "mix"
    elif music_input is not None:
        parts.append(f"[{music_input}:a]aresample=48000,volume=0.6,atrim=duration={total},asetpts=PTS-STARTPTS[bed]")
        base = "bed"
    else:
        parts.append(f"[{silence_input}:a]atrim=duration={total},asetpts=PTS-STARTPTS[bed]")
        base = "bed"
    if sfx_inputs:
        labels = ""
        for k, ((at, _, volume), index) in enumerate(zip(plan.sfx, sfx_inputs)):
            ms = int(at * 1000)
            parts.append(f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,volume={volume:.2f},"
                         f"adelay={ms}|{ms}[fx{k}]")
            labels += f"[fx{k}]"
        parts.append(f"[{base}]{labels}amix=inputs={len(sfx_inputs) + 1}:duration=first:dropout_transition=0:"
                     "normalize=0[withfx]")
        base = "withfx"
    level = loudnorm if probe.has_audio else "anull"
    parts.append(f"[{base}]{level}{_fade_filters(plan, audio=True)}[aout]")
    return ";".join(parts)


async def render(
    src: Path, probe: ProbeInfo, plan: RenderPlan, workdir: Path, fonts_dir: Path, out_name: str = "master.mp4"
) -> Path:
    """Cut, reframe, grade, captions (if plan.ass_file) and audio in one FFmpeg pass."""
    workdir.mkdir(parents=True, exist_ok=True)
    if fonts_dir.is_dir():
        shutil.copytree(fonts_dir, workdir / "fonts", dirs_exist_ok=True)
    else:
        (workdir / "fonts").mkdir(exist_ok=True)

    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src.resolve())]
    music_input = silence_input = None
    next_input = 1
    if plan.music_file and plan.music_file.exists():
        cmd += ["-stream_loop", "-1", "-i", str(plan.music_file.resolve())]
        music_input, next_input = next_input, next_input + 1
    if not probe.has_audio and music_input is None:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        silence_input, next_input = next_input, next_input + 1
    sfx_inputs = []
    for _, sound, _ in plan.sfx:
        cmd += ["-i", str(Path(sound).resolve())]
        sfx_inputs.append(next_input)
        next_input += 1

    master = workdir / out_name
    graph = build_filtergraph(probe, plan, music_input, silence_input, sfx_inputs)
    cmd += [
        "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-r", "30", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart",
        "-t", f"{plan.out_duration:.3f}", master.name,
    ]
    await run(cmd, timeout=180 + plan.out_duration * 10, cwd=str(workdir))
    return master


async def finalize(master: Path, out_duration: float, workdir: Path) -> dict[str, Path]:
    """WhatsApp-sized preview (<= 14.5 MB) and a cover frame from the master."""
    preview = workdir / "preview.mp4"
    kbps = int(min(2500, max(250, PREVIEW_MAX_MB * 8192 / max(out_duration, 1) - 96)))
    if master.stat().st_size <= PREVIEW_MAX_MB * 1_000_000:
        shutil.copyfile(master, preview)  # already small enough for WhatsApp: send full quality
    else:
        await run(
            [
                "ffmpeg", "-y", "-v", "error", "-i", str(master.resolve()), "-vf", "scale=720:1280",
                "-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k",
                "-bufsize", f"{kbps * 2}k", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", preview.name,
            ],
            timeout=120 + out_duration * 6,
            cwd=str(workdir),
        )

    cover = workdir / "cover.jpg"
    await run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{min(1.0, out_duration / 3):.2f}", "-i", str(master.resolve()),
         "-frames:v", "1", "-vf", "scale=540:960", "-q:v", "4", cover.name],
        timeout=60,
        cwd=str(workdir),
    )
    return {"master": master, "preview": preview, "cover": cover}
