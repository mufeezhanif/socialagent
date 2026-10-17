import httpx

from app.integrations.llm import rate_limit_wait
from app.pipeline.editor_agent import apply_rules, apply_tool, auto_text, drop_orphans, initial_state, transcript_lines
from app.pipeline.genres import RECIPES, classify, cut_points, get_recipe, plan_sfx, type_from_request
from app.pipeline.probe import ProbeInfo
from app.pipeline.render_ffmpeg import RenderPlan, build_filtergraph
from app.pipeline.styles import get_preset
from app.pipeline.subtitles import build_ass


def w(text, start, end):
    return {"text": text, "start": start, "end": end}


def words_of(text: str, rate: float = 2.0) -> list[dict]:
    return [w(t, i / rate, i / rate + 0.8 / rate) for i, t in enumerate(text.split())]


def test_type_from_request_and_classify():
    assert type_from_request("make it more energetic please") == "energetic"
    assert type_from_request("this is a brand promo") == "brand"
    assert type_from_request("keep it simple") is None
    calm = words_of("today I went to the market and bought some bread for dinner", rate=2.0)
    assert classify(calm) == "vlog"
    assert classify(calm, notes="a heartfelt tribute to my dad") == "emotional"
    assert classify(words_of("order now and get a discount on our new product")) == "brand"
    assert classify(words_of("one two three four five six seven eight nine ten", rate=4.0)) == "energetic"
    assert get_recipe("nope") is RECIPES["vlog"]


def test_cut_points_only_on_real_cuts():
    segments = [(0.0, 2.0), (3.0, 5.0), (5.1, 8.0), (10.0, 14.0)]  # output 10.9 s
    assert cut_points(segments, 10.9) == [2.0, 6.9]  # the 0.1 s join is not a cut


def test_plan_sfx_per_type():
    energetic = plan_sfx(RECIPES["energetic"], cuts=[2.0, 6.9], highlights=[], emojis=[], out_duration=20,
                         hook=True, punch_start=17.8)
    names = [name for _, name, _ in energetic]
    assert energetic[0][:2] == (0.0, "impact") and names.count("whoosh") == 2 and "riser" in names
    emotional = plan_sfx(RECIPES["emotional"], cuts=[2.0], highlights=[5.0], emojis=[], out_duration=20,
                         hook=True, punch_start=17.8)
    assert {name for _, name, _ in emotional} == {"swell"}
    tutorial = plan_sfx(RECIPES["tutorial"], cuts=[], highlights=[3.0, 3.5, 9.0], emojis=[], out_duration=20,
                        hook=False, punch_start=None)
    assert [t for t, _, _ in tutorial] == [3.0, 9.0]  # spaced out


WORDS = [w("Three", 1.0, 1.3), w("tips", 1.4, 1.8), w("for", 1.9, 2.0), w("better", 2.1, 2.4), w("reels.", 2.5, 2.9),
         w("First,", 5.0, 5.3), w("light.", 5.4, 5.9), w("Second,", 6.5, 6.9), w("sound.", 7.0, 7.5)]


def test_ass_graphics_follow_the_recipe():
    segs = [(0.8, 3.0), (4.9, 9.0)]
    common = dict(words=WORDS, segments=segs, removed=set(), out_duration=6.3, hook_text="Three tips",
                  punchline_text="Follow for more", cta_text="New tips daily", handle="@shop")
    plain = build_ass(preset=get_preset("clean"), **common)
    assert "Sticker," not in plain.split("[Events]")[1] and "@shop" not in plain
    brand = build_ass(preset=get_preset("luxury"), recipe=RECIPES["brand"], **common)
    events = brand.split("[Events]")[1]
    assert ",Card," in events and ",Cta," in events and "@shop" in events and r"\move(" in events
    hype = build_ass(preset=get_preset("hype"), recipe=RECIPES["energetic"], flash_times=[2.2, 5.9], **common)
    flashes = [line for line in hype.splitlines() if line.startswith("Dialogue: 4,")]
    assert len(flashes) == 3  # slam at 0 s, flash on the 2.2 s cut, slam on the end card (5.9 s is inside it)
    sad = build_ass(preset=get_preset("cinematic"), recipe=RECIPES["emotional"], **common)
    assert ",Title," in sad and r"\fad(700,600)" in sad


def test_filtergraph_mixes_sfx_and_look():
    probe = ProbeInfo(duration=10, width=1080, height=1920, fps=30, has_audio=True, vcodec="h264", size_bytes=1)
    plan = RenderPlan(segments=[(0.0, 4.0), (5.0, 9.0)], preset=get_preset("cinematic"), reframe="fill",
                      focus_x=None, ass_file=None, music_file=None, out_duration=8.0,
                      sfx=[(0.0, "swell.wav", 0.3), (1.5, "whoosh.wav", 0.2)], letterbox=True, grain=True,
                      fades=True, drift=True)
    graph = build_filtergraph(probe, plan, None, None, [1, 2])
    assert "adelay=1500|1500" in graph and "amix=inputs=3" in graph
    assert "drawbox" in graph and "noise=" in graph and "fade=t=out:st=7.400" in graph and "afade=t=out" in graph
    assert "crop=1080:1920:x='" in graph and graph.endswith("[aout]")
    bare = build_filtergraph(probe, RenderPlan(segments=[(0.0, 4.0)], preset=get_preset("clean"), reframe="fill",
                                               focus_x=None, ass_file=None, music_file=None, out_duration=4.0),
                             None, None)
    assert "drawbox" not in bare and "amix" not in bare and "fade" not in bare


def state(n: int, video_type: str = "vlog", locked: bool = False) -> dict:
    return initial_state(None, get_recipe(video_type).style, n, locked=locked, motion_allowed=False, motion_on=False,
                         video_type=video_type)


def test_set_look_set_text_and_emphasize():
    s = state(len(WORDS))
    assert apply_tool(s, "set_look", {"video_type": "emotional"}, WORDS, 9).startswith("ok")
    assert s["video_type"] == "emotional" and s["style"] == "cinematic" and s["music"] is True
    assert apply_tool(s, "set_look", {"video_type": "disco"}, WORDS, 9).startswith("error")
    locked = state(len(WORDS), locked=True)
    apply_tool(locked, "set_look", {"video_type": "energetic"}, WORDS, 9)
    assert locked["style"] == "clean" and locked["video_type"] == "energetic"  # the user's style wins
    apply_tool(s, "set_text", {"hook": "Three tips", "punchline": "Follow"}, WORDS, 9)
    apply_tool(s, "set_text", {"cta": "Link in bio"}, WORDS, 9)
    assert (s["hook_text"], s["punchline_text"], s["cta_text"]) == ("Three tips", "Follow", "Link in bio")
    assert apply_tool(s, "emphasize", {"words": [0, 6], "emoji": [{"word": 6, "emoji": "💡"}]}, WORDS, 9).startswith("ok")
    assert s["highlight_word_indices"] == [0, 6] and s["emoji_moments"][0]["word_index"] == 6


def test_rules_pick_up_a_type_request():
    s = state(len(WORDS))
    apply_rules(s, ["make it more energetic"], WORDS, 9)
    assert s["video_type"] == "energetic" and s["style"] == "hype"


def test_drop_orphans_removes_stranded_fragments():
    s = initial_state(None, "clean", len(WORDS), locked=False, motion_allowed=False, motion_on=False, max_cut=0.9)
    apply_tool(s, "remove_words", {"start_word": 0, "end_word": 1, "reason": "x"}, WORDS, 9)
    apply_tool(s, "remove_words", {"start_word": 4, "end_word": 6, "reason": "x"}, WORDS, 9)
    trace = drop_orphans(s, WORDS, 9)  # "for better" is left alone between two cuts
    assert len(trace) == 1 and "2" in trace[0]


def test_transcript_lines_are_compact():
    units = [{"first_word": 0, "last_word": 4, "avg_logprob": -0.1, "compression_ratio": 1.0, "no_speech_prob": 0.0},
             {"first_word": 5, "last_word": 8, "avg_logprob": -0.2, "compression_ratio": 2.6, "no_speech_prob": 0.0}]
    text = transcript_lines(WORDS, units)
    assert text.splitlines()[0] == "[1.0] 0 Three 1 tips 2 for 3 better 4 reels."
    assert text.splitlines()[1].startswith("[5.0?] 5 First,")


def test_rate_limit_wait_parses_groq_messages():
    def resp(body: str, headers: dict | None = None) -> httpx.Response:
        return httpx.Response(429, text=body, headers=headers or {})

    assert rate_limit_wait(resp("Please try again in 7m12.5s. Need more tokens?")) == 432.5
    assert rate_limit_wait(resp("Please try again in 450ms")) == 0.45
    assert rate_limit_wait(resp("slow down", {"retry-after": "3"})) == 3.0
    assert rate_limit_wait(resp("slow down")) is None


def test_rules_fallback_writes_a_hook_and_end_card():
    s = state(len(WORDS) + 2)
    auto_text(s, [w("Hi", 0.0, 0.2), w("guys.", 0.3, 0.5)] + WORDS, {"cta": "Follow for daily tips"})  # greeting skipped
    assert s["hook_text"] == "Three tips for better reels" and s["punchline_text"] == "Follow for daily tips"
    urdu = state(len(WORDS))
    assert auto_text(urdu, WORDS, {}, english=False) == [] and urdu["hook_text"] in ("", None)
