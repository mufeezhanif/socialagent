"""One FFmpeg pass: cut + zoom alternation + 9:16 reframe + grade + captions + cleaned/levelled audio (+ music bed)."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.cuts import Segment
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


def _even(value: float) -> int:
    return max(2, int(value) // 2 * 2)


def choose_reframe(probe: ProbeInfo, crop_mode: str, focus_x: float | None) -> str:
    ratio = probe.width / max(probe.height, 1)
    if ratio <= 0.8:
        return "fill"  # already vertical-ish: scale and trim the edges
    if crop_mode == "crop" or (crop_mode == "auto" and focus_x is not None):
        return "crop"
    return "blur_pad"


def build_filtergraph(probe: ProbeInfo, plan: RenderPlan, music_input: int | None, silence_input: int | None) -> str:
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

    post = [plan.preset.grade] if plan.preset.grade else []
    if plan.ass_file:
        post.append(f"ass={plan.ass_file.name}:fontsdir=fonts")
    post += ["fps=30", "format=yuv420p"]
    parts.append("[vr]" + ",".join(post) + "[vout]")

    total = plan.out_duration
    loudnorm = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000"
    if probe.has_audio:
        parts.append("[ac]highpass=f=80,afftdn=nf=-25,acompressor=threshold=0.125:ratio=3:attack=5:release=150:makeup=2[voice]")
        if music_input is not None:
            parts.append(
                "[voice]asplit[vmix][vkey];"
                f"[{music_input}:a]aresample=48000,volume=0.22[mus];"
                "[mus][vkey]sidechaincompress=threshold=0.04:ratio=10:attack=15:release=350[duck];"
                "[vmix][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix];"
                f"[mix]{loudnorm}[aout]"
            )
        else:
            parts.append(f"[voice]{loudnorm}[aout]")
    elif music_input is not None:
        parts.append(f"[{music_input}:a]aresample=48000,volume=0.6,atrim=duration={total},asetpts=PTS-STARTPTS[aout]")
    else:
        parts.append(f"[{silence_input}:a]atrim=duration={total},asetpts=PTS-STARTPTS[aout]")
    return ";".join(parts)


async def render(src: Path, probe: ProbeInfo, plan: RenderPlan, workdir: Path, fonts_dir: Path) -> dict[str, Path]:
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
        silence_input = next_input

    master = workdir / "master.mp4"
    graph = build_filtergraph(probe, plan, music_input, silence_input)
    cmd += [
        "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-r", "30", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart",
        "-t", f"{plan.out_duration:.3f}", master.name,
    ]
    await run(cmd, timeout=180 + plan.out_duration * 10, cwd=str(workdir))

    preview = workdir / "preview.mp4"
    kbps = int(min(2500, max(250, PREVIEW_MAX_MB * 8192 / max(plan.out_duration, 1) - 96)))
    await run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", master.name, "-vf", "scale=720:1280",
            "-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.3)}k",
            "-bufsize", f"{kbps * 2}k", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", preview.name,
        ],
        timeout=120 + plan.out_duration * 6,
        cwd=str(workdir),
    )

    cover = workdir / "cover.jpg"
    await run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{min(1.0, plan.out_duration / 3):.2f}", "-i", master.name,
         "-frames:v", "1", "-vf", "scale=540:960", "-q:v", "4", cover.name],
        timeout=60,
        cwd=str(workdir),
    )
    return {"master": master, "preview": preview, "cover": cover}
