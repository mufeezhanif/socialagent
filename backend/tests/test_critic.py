import asyncio
from pathlib import Path

from app.integrations import llm
from app.pipeline import critic
from app.pipeline.critic import CriticReport, Issue
from app.pipeline.edit import EditOutput, critic_round


def words(*spec: tuple[str, float, float]) -> list[dict]:
    return [{"text": t, "start": s, "end": e, "i": i} for i, (t, s, e) in enumerate(spec)]


def test_length_vs_target():
    assert critic.check_length(50, 30)[0].severity == "high"
    assert critic.check_length(33, 30) == []
    assert critic.check_length(20, 30)[0].severity == "low"
    assert critic.check_length(50, None) == []


def test_slow_hook_flagged_only_with_a_hook():
    w = words(("hello", 3.0, 3.4), ("world", 3.5, 4.0))
    seg = [(0.0, 5.0)]
    assert critic.check_hook({"hook_text": "Big news"}, w, seg, set())[0].severity == "high"
    assert critic.check_hook({"hook_text": ""}, w, seg, set()) == []
    assert critic.check_hook({"hook_text": "Big news"}, w, [(2.8, 5.0)], set()) == []


def test_short_segments_and_clipped_words():
    assert critic.check_segments([(0, 5), (6, 9)]) == []
    assert critic.check_segments([(0, 0.5), (1, 1.4), (2, 2.3), (3, 9)])[0].severity == "high"
    assert critic.check_segments([(0, 0.5), (1, 9), (10, 20), (21, 30)])[0].severity == "low"
    w = words(("hello", 0.0, 1.0), ("there", 1.2, 2.0))
    assert critic.check_cut_words(w, [(0.0, 0.5), (1.1, 2.0)], set())  # the cut at 0.5 lands inside "hello"
    assert critic.check_cut_words(w, [(0.0, 1.1), (1.1, 2.0)], set()) == []


def test_ungrounded_text():
    sources = ["we bake fresh sourdough every morning"]
    assert critic.check_text({"hook_text": "Fresh sourdough daily"}, sources) == []
    bad = critic.check_text({"hook_text": "Win 500 dollars today"}, sources)
    assert bad and bad[0].severity == "high"
    assert critic.check_text({"cta_text": "Follow for more tips"}, sources)[0].severity == "high"


def test_review_without_llm_is_deterministic_and_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "any_configured", lambda: False)
    w = words(("hello", 3.0, 3.4), ("world", 3.5, 4.0))
    report = asyncio.run(critic.review(
        preview=tmp_path / "missing.mp4", storyboard={"hook_text": "Big news"}, words=w, segments=[(0.0, 5.0)],
        removed=set(), out_duration=5.0, probe_duration=5.0, notes=[""], brand={}, workdir=tmp_path))
    assert report.verdict == "revise" and not report.llm_used and report.high

    async def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(llm, "any_configured", lambda: True)
    monkeypatch.setattr(llm, "structured", boom)
    monkeypatch.setattr(critic, "sample_frames", boom)
    report = asyncio.run(critic.review(
        preview=tmp_path / "missing.mp4", storyboard={}, words=w, segments=[(0.0, 5.0)], removed=set(),
        out_duration=5.0, probe_duration=5.0, notes=[], brand=None, workdir=tmp_path))
    assert report.verdict == "ship" and not report.llm_used


def make_out(tag: str) -> EditOutput:
    p = Path(tag)
    return EditOutput(master=p, preview=p, cover=p, probe={}, transcript={}, face_x=None, storyboard={"tag": tag},
                      from_ai=True, duration_in=10, duration_out=8, summary=["Vertical 9:16"], question="")


def run_round(report: CriticReport, again):
    calls = {"review": 0}

    async def review(out):
        calls["review"] += 1
        return report

    out = asyncio.run(critic_round(make_out("first"), ["tighter"], review, again))
    return out, calls


def test_round_revises_once_with_critic_fixes():
    seen = []

    async def again(requests, previous):
        seen.append((requests, previous))
        return make_out("second")

    report = CriticReport(verdict="revise", issues=[Issue(severity="high", problem="Slow hook", fix="Trim 3s")])
    out, calls = run_round(report, again)
    assert out.storyboard == {"tag": "second"} and calls["review"] == 1 and len(seen) == 1
    assert seen[0][0] == ["tighter", "Critic note: Trim 3s"] and seen[0][1] == {"tag": "first"}
    assert out.critic["revised"] is True and out.summary[-1] == "Quality check: fixed slow hook"


def test_round_passes_without_high_issues_and_survives_failures():
    async def again(requests, previous):
        raise AssertionError("must not run")

    low = CriticReport(issues=[Issue(severity="low", problem="Meh", fix="x")])
    out, _ = run_round(low, again)
    assert out.storyboard == {"tag": "first"} and out.summary[-1] == "Quality check: passed"

    async def broken(requests, previous):
        raise RuntimeError("render failed")

    high = CriticReport(verdict="revise", issues=[Issue(severity="high", problem="Slow hook", fix="Trim")])
    out, _ = run_round(high, broken)
    assert out.storyboard == {"tag": "first"} and out.critic["revised"] is False
    assert out.summary[-1].startswith("Quality check: flagged")

    async def same(requests, previous):
        return None  # editor changed nothing

    out, _ = run_round(high, same)
    assert out.critic["revised"] is False
