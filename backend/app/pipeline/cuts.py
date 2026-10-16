"""Decide which parts of the original clip survive: keep speech, drop dead air, filler words and removed ranges."""

import re

Segment = tuple[float, float]

FILLERS = {"um", "umm", "uh", "uhh", "uhm", "erm", "er", "hmm", "mm", "mhm", "ah", "eh"}
_NON_WORD = re.compile(r"[^\w']+")


def normalize_word(text: str) -> str:
    return _NON_WORD.sub("", text.lower())


def is_filler(text: str) -> bool:
    return normalize_word(text) in FILLERS


def _subtract(intervals: list[list[float]], start: float, end: float) -> list[list[float]]:
    out: list[list[float]] = []
    for s, e in intervals:
        if end <= s or start >= e:
            out.append([s, e])
            continue
        if start > s:
            out.append([s, start])
        if end < e:
            out.append([end, e])
    return out


def keep_segments(
    words: list[dict],
    duration: float,
    removed: set[int] | frozenset[int] = frozenset(),
    *,
    trim_start: float = 0.0,
    trim_end: float = 0.0,
    pad_before: float = 0.08,
    pad_after: float = 0.14,
    max_gap: float = 0.45,
    min_len: float = 0.3,
) -> list[Segment]:
    """Segments (original timeline) to keep, in order."""
    lo = min(max(0.0, trim_start), duration)
    hi = max(lo, duration - max(0.0, trim_end))
    if hi - lo < 1.0:
        lo, hi = 0.0, duration
    whole = [(round(lo, 3), round(hi, 3))]

    excluded = {i for i, w in enumerate(words) if i in removed or is_filler(w["text"])}
    kept = [w for i, w in enumerate(words) if i not in excluded and w["end"] > lo and w["start"] < hi]
    if not kept:
        return whole

    intervals: list[list[float]] = []
    for w in kept:
        s, e = max(lo, w["start"] - pad_before), min(hi, w["end"] + pad_after)
        if e - s <= 0.02:
            continue
        if intervals and s - intervals[-1][1] <= max_gap:
            intervals[-1][1] = max(intervals[-1][1], e)
        else:
            intervals.append([s, e])

    for i in sorted(excluded):
        w = words[i]
        intervals = _subtract(intervals, w["start"], w["end"])

    segments = [(round(s, 3), round(e, 3)) for s, e in intervals if e - s >= min_len]
    if not segments or sum(e - s for s, e in segments) < 1.0:
        return whole
    return segments


def output_duration(segments: list[Segment]) -> float:
    return round(sum(e - s for s, e in segments), 3)


def map_span(start: float, end: float, segments: list[Segment]) -> tuple[float, float] | None:
    """Map an original-timeline span onto the edited timeline (largest overlapping segment wins)."""
    best: tuple[float, float, float] | None = None
    offset = 0.0
    for s, e in segments:
        overlap = min(end, e) - max(start, s)
        if overlap > 0 and (best is None or overlap > best[0]):
            best = (overlap, offset + max(start, s) - s, offset + min(end, e) - s)
        offset += e - s
    if best is None or best[2] - best[1] < 0.05:
        return None
    return round(best[1], 3), round(best[2], 3)


def map_time(t: float, segments: list[Segment]) -> float | None:
    offset = 0.0
    for s, e in segments:
        if s <= t <= e:
            return round(offset + t - s, 3)
        offset += e - s
    return None
