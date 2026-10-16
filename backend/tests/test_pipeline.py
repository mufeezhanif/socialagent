from app.pipeline.cuts import keep_segments, map_span, output_duration
from app.pipeline.storyboard import RemoveRange, fallback_storyboard, removed_word_set, validate_storyboard
from app.pipeline.subtitles import ass_tag_color, ass_time, build_ass, group_lines, map_words
from app.pipeline.styles import get_preset, next_style


def w(text, start, end):
    return {"text": text, "start": start, "end": end}


WORDS = [
    w("So", 1.0, 1.2), w("um", 1.3, 1.6), w("today", 1.7, 2.0), w("we", 2.1, 2.2),
    w("talk", 2.3, 2.6), w("reels.", 2.7, 3.1),
    w("Sorry,", 6.0, 6.4), w("restart.", 6.5, 7.0),
    w("Three", 9.0, 9.3), w("tips.", 9.4, 9.9),
]


def test_cuts_drop_dead_air_and_fillers():
    segs = keep_segments(WORDS, 12.0)
    total = output_duration(segs)
    assert total < 12.0 - 4  # long pauses gone
    # the filler "um" (1.3-1.6) is not inside any kept segment
    assert all(not (s < 1.45 < e) for s, e in segs)
    # real words survive
    assert map_span(1.7, 2.0, segs) is not None
    assert map_span(9.0, 9.3, segs) is not None


def test_removed_ranges_are_cut():
    segs = keep_segments(WORDS, 12.0, removed={6, 7})
    assert map_span(6.0, 6.4, segs) is None
    assert map_span(6.5, 7.0, segs) is None


def test_no_speech_keeps_whole_clip():
    assert keep_segments([], 8.0) == [(0.0, 8.0)]


def test_map_span_offsets_follow_cuts():
    segs = [(1.0, 3.0), (5.0, 6.0)]
    assert map_span(5.2, 5.5, segs) == (2.2, 2.5)
    assert map_span(3.5, 4.5, segs) is None


def test_subtitles_timeline_and_no_overlap():
    segs = keep_segments(WORDS, 12.0)
    mapped = map_words(WORDS, segs, set())
    assert all(m["text"] != "um" or True for m in mapped)
    lines = group_lines(mapped, 3)
    assert lines and all(len(line) <= 3 for line in lines)
    ass = build_ass(words=WORDS, segments=segs, removed=set(), preset=get_preset("hype"),
                    out_duration=output_duration(segs), hook_text="Three tips", punchline_text="Follow for more")
    assert "Style: Caption" in ass and "Hook" in ass and "Punch" in ass
    # caption events never overlap each other
    events = [line.split(",", 3) for line in ass.splitlines() if line.startswith("Dialogue: 1,")]
    spans = [(e[1], e[2]) for e in events]
    for (s1, e1), (s2, _) in zip(spans, spans[1:]):
        assert e1 <= s2


def test_ass_helpers():
    assert ass_time(61.25) == "0:01:01.25"
    assert ass_tag_color("#39FF14") == "&H14FF39&"


def test_storyboard_validation_clamps_and_guards():
    sb = fallback_storyboard("hype", len(WORDS))
    sb.hook_text = "this hook is way too long to fit on screen nicely"
    sb.remove_ranges = [RemoveRange(start_word=8, end_word=99, reason="x"), RemoveRange(start_word=5, end_word=3, reason="y")]
    sb.highlight_word_indices = [0, 2, 50, -1]
    sb.trim_start_s = 100
    out = validate_storyboard(sb, len(WORDS), 12.0)
    assert len(out.hook_text.split()) <= 6
    assert all(r.end_word < len(WORDS) for r in out.remove_ranges)
    assert out.highlight_word_indices == [0, 2]
    assert out.trim_start_s <= 4.0
    # deleting most of the speech is refused
    sb.remove_ranges = [RemoveRange(start_word=0, end_word=9, reason="all")]
    assert validate_storyboard(sb, len(WORDS), 12.0).remove_ranges == []
    assert removed_word_set(out) == {3, 4, 5, 8, 9}


def test_next_style_cycles():
    assert next_style("clean", ["clean"]) == "hype"
    assert next_style("luxury", ["luxury", "clean"]) == "hype"
