"""Run the full edit on a test video and score it against an answer key.

    python scripts/eval_edit.py samples/bakery.mp4 --expected samples/bakery.expected.json --out samples/out/eval

Scores two things:
  1. Editorial decisions: which parts of the answer key were kept / cut (from the edit's own cut list).
  2. Cut precision: the rendered output is re-transcribed and compared with the words the edit meant to keep,
     so clipped words and leftover fillers show up.
"""

import argparse
import asyncio
import difflib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.integrations import llm  # noqa: E402
from app.pipeline.cuts import is_filler, map_span, normalize_word  # noqa: E402
from app.pipeline.edit import EditInput, run_edit  # noqa: E402
from app.pipeline.transcribe import transcribe  # noqa: E402


def toks(text: str) -> list[str]:
    return [t for t in (normalize_word(x) for x in text.split()) if t]


def loudness(path: Path) -> float | None:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                       capture_output=True, text=True, errors="ignore")
    m = re.findall(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", r.stderr)
    return float(m[-1]) if m else None


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,width,height,r_frame_rate",
                          "-of", "json", str(path)], capture_output=True, text=True).stdout
    data = json.loads(out)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    return {"duration": round(float(data["format"]["duration"]), 2), "size_mb": round(int(data["format"]["size"]) / 1e6, 2),
            "resolution": f"{video['width']}x{video['height']}", "fps": video.get("r_frame_rate")}


def contact_sheet(src: Path, master: Path, out: Path, src_dur: float, out_dur: float) -> None:
    """Top row: input frames. Bottom row: output frames (same relative positions)."""
    tiles = []
    for i, frac in enumerate((0.05, 0.3, 0.55, 0.8)):
        a, b = out.parent / f"_in{i}.jpg", out.parent / f"_out{i}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{src_dur * frac:.2f}", "-i", str(src), "-frames:v", "1",
                        "-vf", "scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2:color=0x222222", str(a)], check=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{out_dur * frac:.2f}", "-i", str(master), "-frames:v", "1",
                        "-vf", "scale=360:640", str(b)], check=True)
        tiles += [a, b]
    inputs = []
    for t in tiles:
        inputs += ["-i", str(t)]
    grid = "".join(f"[{i * 2}:v]" for i in range(4)) + "hstack=inputs=4[top];" + \
           "".join(f"[{i * 2 + 1}:v]" for i in range(4)) + "hstack=inputs=4[bot];[top][bot]vstack[v]"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", grid, "-map", "[v]", str(out)], check=True)
    for t in tiles:
        t.unlink()


def align_script(script_segments: list[dict], words: list[dict]) -> list[int | None]:
    """Segment index for each transcript word (monotonic alignment of script tokens to Whisper tokens)."""
    script_tokens, owner = [], []
    for si, seg in enumerate(script_segments):
        for t in toks(seg["text"]):
            script_tokens.append(t)
            owner.append(si)
    word_tokens = [normalize_word(w["text"]) for w in words]
    result: list[int | None] = [None] * len(words)
    sm = difflib.SequenceMatcher(None, script_tokens, word_tokens, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("equal", "replace"):
            for k in range(j2 - j1):
                result[j1 + k] = owner[min(i1 + k, i2 - 1)]
    # fill gaps from neighbours (e.g. a filler Whisper heard slightly differently)
    for j in range(len(result)):
        if result[j] is None:
            result[j] = result[j - 1] if j else next((r for r in result if r is not None), None)
    return result


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--expected")
    ap.add_argument("--out", default="samples/out/eval")
    ap.add_argument("--style", default=None)
    ap.add_argument("--change", action="append", default=[])
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    started = time.time()
    result = await run_edit(EditInput(src=src, workdir=out / "work", style_request=args.style, change_requests=args.change))
    edit_seconds = round(time.time() - started, 1)

    words = result.transcript["words"]
    sb = result.storyboard
    removed = set()
    for r in sb["remove_ranges"]:
        removed.update(range(r["start_word"], r["end_word"] + 1))
    from app.pipeline.cuts import keep_segments

    segments = keep_segments(words, result.duration_in, removed, trim_start=sb["trim_start_s"], trim_end=sb["trim_end_s"])
    kept_flags = [i not in removed and map_span(w["start"], w["end"], segments) is not None for i, w in enumerate(words)]

    # 2) cut precision: what the output actually says vs what the edit meant to keep
    out_words = (await transcribe(str(result.master)))["words"]
    intended = [normalize_word(w["text"]) for w, k in zip(words, kept_flags) if k and not is_filler(w["text"])]
    heard = [normalize_word(w["text"]) for w in out_words if not is_filler(w["text"])]
    sm = difflib.SequenceMatcher(None, intended, heard, autojunk=False)
    missing, extra = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("delete", "replace"):
            missing += intended[i1:i2]
        if tag in ("insert", "replace"):
            extra += heard[j1:j2]
    leftover_fillers = [w["text"] for w in out_words if is_filler(w["text"])]

    # 1) editorial decisions vs the answer key
    rows, correct = [], 0
    if args.expected:
        key = json.loads(Path(args.expected).read_text(encoding="utf-8"))["segments"]
        owner = align_script(key, words)
        for si, seg in enumerate(key):
            idx = [j for j, o in enumerate(owner) if o == si]
            kept = sum(kept_flags[j] for j in idx) / len(idx) if idx else 0.0
            actual = "keep" if kept >= 0.5 else "cut"
            ok = actual == seg["expect"]
            correct += ok
            rows.append({"text": seg["text"], "expected": seg["expect"], "why": seg.get("why", ""),
                         "kept_fraction": round(kept, 2), "actual": actual, "ok": ok})

    contact_sheet(src, result.master, out / "compare.jpg", result.duration_in, result.duration_out)
    inp, outp = probe(src), probe(result.master)
    inp["loudness_lufs"], outp["loudness_lufs"] = loudness(src), loudness(result.master)

    report = {
        "editor": result.editor,
        "llm_providers_configured": llm.names(),
        "edit_seconds": edit_seconds,
        "input": inp,
        "output": outp,
        "summary": result.summary,
        "settings": {k: sb[k] for k in ("style", "hook_text", "punchline_text", "cta_text", "crop_mode",
                                        "captions_enabled", "caption_position", "music", "highlight_word_indices")},
        "cuts": [{"words": f"{r['start_word']}-{r['end_word']}", "reason": r["reason"],
                  "text": " ".join(w["text"] for w in words[r["start_word"]: r["end_word"] + 1])} for r in sb["remove_ranges"]],
        "kept_segments_source_time": segments,
        "decisions": rows,
        "decision_accuracy": f"{correct}/{len(rows)}" if rows else None,
        "precision": {
            "intended_words": len(intended),
            "heard_in_output": len(heard),
            "word_match_ratio": round(sm.ratio(), 3),
            "missing_or_clipped_words": missing,
            "unexpected_words": extra,
            "leftover_fillers": leftover_fillers,
        },
        "trace": result.trace,
        "input_transcript": " ".join(("~~" + w["text"] + "~~") if not k else w["text"] for w, k in zip(words, kept_flags)),
        "output_transcript": " ".join(w["text"] for w in out_words),
        "files": {"master": str(result.master), "preview": str(result.preview), "compare": str(out / "compare.jpg")},
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
