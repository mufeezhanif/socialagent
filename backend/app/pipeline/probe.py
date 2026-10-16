import json
from dataclasses import asdict, dataclass

from app.pipeline.proc import run


@dataclass
class ProbeInfo:
    duration: float
    width: int  # display width (after rotation)
    height: int  # display height (after rotation)
    fps: float
    has_audio: bool
    vcodec: str
    size_bytes: int

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProbeInfo":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__})


def _fps(rate: str | None) -> float:
    if not rate or rate in ("0/0", "0"):
        return 30.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        return float(num) / float(den) if float(den) else 30.0
    return float(rate)


def _rotation(stream: dict) -> int:
    tags = stream.get("tags") or {}
    if "rotate" in tags:
        return int(float(tags["rotate"])) % 360
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return int(float(side["rotation"])) % 360
    return 0


async def probe(path: str) -> ProbeInfo:
    out = await run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        timeout=60,
    )
    data = json.loads(out)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise ValueError("No video stream found")
    audio = any(s.get("codec_type") == "audio" for s in streams)
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    if _rotation(video) in (90, 270):
        width, height = height, width
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    return ProbeInfo(
        duration=round(duration, 3),
        width=width,
        height=height,
        fps=round(_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")), 3),
        has_audio=audio,
        vcodec=video.get("codec_name", ""),
        size_bytes=int(data.get("format", {}).get("size") or 0),
    )
