from pathlib import Path

from app.pipeline.proc import run


async def sample_frames(src: str, duration: float, out_dir: Path, count: int = 8) -> list[Path]:
    """Evenly spaced JPEG frames (<= 640 px) for the director to look at."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f_*.jpg"):
        old.unlink()
    rate = max(count / max(duration, 0.5), 0.05)
    await run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", src,
            "-vf", f"fps={rate:.4f},scale=640:640:force_original_aspect_ratio=decrease",
            "-frames:v", str(count), "-q:v", "5", str(out_dir / "f_%02d.jpg"),
        ],
        timeout=120,
    )
    return sorted(out_dir.glob("f_*.jpg"))
