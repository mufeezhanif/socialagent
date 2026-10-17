"""Critic agent: reviews the editor agent's rendered reel before the human sees it.

Cheap deterministic checks first, then one structured LLM call that looks at frames from the rendered preview. High
severity issues come back to the editor as concrete fix instructions (one revision at most, decided by the caller).
Nothing here raises: with no LLM, or on any failure, the deterministic result is returned.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.integrations import llm
from app.pipeline.cuts import Segment, is_filler
from app.pipeline.editor_agent import grounded_cta, parse_target
from app.pipeline.frames import sample_frames

log = logging.getLogger(__name__)

TARGET_TOLERANCE = 0.2  # allowed deviation from a requested length
HOOK_WINDOW_S = 2.0  # speech (or the hook line) should start within this many seconds
MIN_SEGMENT_S = 1.0
LLM_TIMEOUT_S = 45.0
MAX_ISSUES = 4


class Issue(BaseModel):
    severity: Literal["high", "low"] = Field(description="high = a viewer would notice and it is worth a re-edit")
    problem: str = Field(description="What is wrong, one short line")
    fix: str = Field(description="A concrete one-line instruction for the editor, e.g. 'Cut the first 3 seconds'")


class CriticVerdict(BaseModel):
    verdict: Literal["ship", "revise"]
    issues: list[Issue] = Field(description="At most 3 issues, most important first")


@dataclass
class CriticReport:
    verdict: str = "ship"
    issues: list[Issue] = field(default_factory=list)
    seconds: float = 0.0
    llm_used: bool = False

    @property
    def high(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "high"]

    def to_dict(self, revised: bool = False) -> dict:
        return {"verdict": self.verdict, "issues": [i.model_dump() for i in self.issues], "revised": revised,
                "seconds": round(self.seconds, 1), "llm": self.llm_used}


def _out_time(t: float, segments: list[Segment]) -> float | None:
    """Source time -> time in the edited video (None if that moment was cut)."""
    elapsed = 0.0
    for s, e in segments:
        if s <= t <= e:
            return elapsed + (t - s)
        elapsed += e - s
    return None


def check_length(out_duration: float, target: float | None) -> list[Issue]:
    if not target:
        return []
    if out_duration > target * (1 + TARGET_TOLERANCE):
        return [Issue(severity="high", problem=f"Runs {out_duration:.0f}s but {target:.0f}s was asked for",
                      fix=f"Cut it down to about {target:.0f} seconds by removing the weakest sentences")]
    if out_duration < target * (1 - TARGET_TOLERANCE):
        return [Issue(severity="low", problem=f"Only {out_duration:.0f}s when {target:.0f}s was asked for",
                      fix=f"Keep more of the content so it runs about {target:.0f} seconds")]
    return []


def check_hook(storyboard: dict, words: list[dict], segments: list[Segment], removed: set[int]) -> list[Issue]:
    """With a hook line set, the speech should start right away (the hook sits over the first ~2.5 s)."""
    if not (storyboard.get("hook_text") or "").strip() or not segments:
        return []
    first = next((w for i, w in enumerate(words) if i not in removed and not is_filler(w["text"])
                  and _out_time(w["start"], segments) is not None), None)
    if first is None:
        return []
    start = _out_time(first["start"], segments) or 0.0
    if start > HOOK_WINDOW_S:
        return [Issue(severity="high", problem=f"Slow hook: nothing is said until {start:.1f}s",
                      fix=f"Trim the first {start - 0.4:.1f} seconds so the speech starts straight away")]
    return []


def check_segments(segments: list[Segment]) -> list[Issue]:
    short = [s for s in segments if s[1] - s[0] < MIN_SEGMENT_S]
    if len(segments) < 2 or not short:
        return []
    bad = len(short) >= 3 or len(short) / len(segments) > 0.3
    return [Issue(severity="high" if bad else "low", problem=f"{len(short)} clips under {MIN_SEGMENT_S:.0f}s between cuts (choppy)",
                  fix="Remove fewer short fragments so the cuts feel less jumpy")]


def check_cut_words(words: list[dict], segments: list[Segment], removed: set[int]) -> list[Issue]:
    """Kept words that a cut lands inside of (the word is clipped)."""
    clipped = 0
    for i, w in enumerate(words):
        if i in removed or is_filler(w["text"]) or w["end"] - w["start"] < 0.15:
            continue
        lo, hi = w["start"] + 0.05, w["end"] - 0.05
        if any(lo < b < hi for s, e in segments for b in (s, e)):
            clipped += 1
    if not clipped:
        return []
    return [Issue(severity="high" if clipped >= 2 else "low", problem=f"{clipped} word(s) cut off mid-way",
                  fix="Move the cuts so no spoken word is clipped")]


_FIGURE_RE = re.compile(r"[$€£]\s?\d|\d")


def check_text(storyboard: dict, sources: list[str]) -> list[Issue]:
    """On-screen text should come from what was said, the notes or the brand kit; invented figures are the worst case."""
    text = " ".join(sources).lower()
    issues: list[Issue] = []
    for field_name, label in (("hook_text", "Hook"), ("punchline_text", "End card"), ("cta_text", "Call to action")):
        line = (storyboard.get(field_name) or "").strip()
        if not line or grounded_cta(line, sources):
            continue
        figures = [m for m in re.findall(r"[$€£]?\s?\d[\d.,%]*", line) if m.strip(" $€£") not in text]
        severe = bool(figures) or field_name == "cta_text"
        issues.append(Issue(severity="high" if severe else "low", problem=f"{label} \"{line[:40]}\" is not from the video or notes",
                            fix=f"Rewrite the {label.lower()} using only what was said or asked for, or leave it empty"))
    for field_name, label in (("hook_text", "Hook"), ("punchline_text", "End card")):
        line = (storyboard.get(field_name) or "").strip()
        if line and _FIGURE_RE.search(line) and not any(f in text for f in re.findall(r"\d[\d.,]*", line)):
            if not any(i.problem.startswith(label) for i in issues):
                issues.append(Issue(severity="high", problem=f"{label} states a figure that was never said",
                                    fix=f"Rewrite the {label.lower()} without numbers that are not in the video"))
    return issues


def deterministic_checks(*, storyboard: dict, words: list[dict], segments: list[Segment], removed: set[int],
                         out_duration: float, target: float | None, sources: list[str]) -> list[Issue]:
    return (check_length(out_duration, target) + check_hook(storyboard, words, segments, removed)
            + check_segments(segments) + check_cut_words(words, segments, removed) + check_text(storyboard, sources))


SYSTEM = """You are a strict but fair quality reviewer for Instagram Reels edited by an AI editor from a creator's raw phone \
clip. You see frames from the finished reel (in order), the kept transcript and the on-screen text lines. Judge only what \
a viewer would notice: the subject cut out of frame, unreadable or overlapping on-screen text, a hook or end card that \
misstates what was said, a rambling or pointless opening, a missing key point. Do not nitpick style or taste. Mark an \
issue "high" only if it is a real defect worth another edit; otherwise "low", or return no issues. Each fix must be one \
concrete instruction the editor can act on with its tools (trim, cut a sentence, rewrite the hook, change crop or \
caption position). Never ask for a call to action, music or effects the creator did not request. If it is good, \
verdict "ship" with no issues."""


def _kept_text(words: list[dict], removed: set[int], limit: int = 1500) -> str:
    return " ".join(w["text"] for i, w in enumerate(words) if i not in removed and not is_filler(w["text"]))[:limit]


async def _llm_review(preview: Path, storyboard: dict, kept: str, found: list[Issue], out_duration: float,
                      workdir: Path) -> list[Issue] | None:
    try:
        frames = await sample_frames(str(preview), out_duration, workdir / "critic_frames", count=3)
    except Exception as exc:
        log.warning("critic frames failed: %s", exc)
        frames = []
    text = (
        f"Reel length: {out_duration:.0f}s\nHook: {storyboard.get('hook_text') or '(none)'}\n"
        f"End card: {storyboard.get('punchline_text') or '(none)'}\nCall to action: {storyboard.get('cta_text') or '(none)'}\n"
        f"Captions: {'on' if storyboard.get('captions_enabled') else 'off'}\nScene: {storyboard.get('scene_description') or ''}\n"
        f"Kept transcript: {kept or '(no speech)'}\n"
        f"Already flagged by automatic checks (do not repeat): {[i.problem for i in found] or 'none'}"
    )
    try:
        result = await asyncio.wait_for(
            llm.structured(CriticVerdict, system=SYSTEM, text=text, images=frames, effort="low", max_tokens=600),
            LLM_TIMEOUT_S)
    except Exception as exc:
        log.warning("critic llm failed: %s", exc)
        return None
    return list(result.issues[:3]) if result else None


async def review(*, preview: Path, storyboard: dict, words: list[dict], segments: list[Segment], removed: set[int],
                 out_duration: float, probe_duration: float, notes: list[str], brand: dict | None,
                 workdir: Path, target: float | None = None) -> CriticReport:
    """Review a finished edit. Never raises."""
    started = time.time()
    report = CriticReport()
    try:
        brand_text = [v for v in (brand or {}).values() if isinstance(v, str)]
        sources = [*notes, *brand_text, " ".join(w["text"] for w in words)]
        target = target or parse_target(notes)
        if target and target >= probe_duration - 1:
            target = None
        issues = deterministic_checks(storyboard=storyboard, words=words, segments=segments, removed=removed,
                                      out_duration=out_duration, target=target, sources=sources)
        if llm.any_configured():
            extra = await _llm_review(preview, storyboard, _kept_text(words, removed), issues, out_duration, workdir)
            if extra is not None:
                report.llm_used = True
                issues += extra
        issues.sort(key=lambda i: i.severity != "high")
        report.issues = issues[:MAX_ISSUES]
        report.verdict = "revise" if report.high else "ship"
    except Exception as exc:
        log.warning("critic failed, shipping as is: %s", exc)
        report = CriticReport()
    report.seconds = time.time() - started
    return report
