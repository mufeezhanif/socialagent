import asyncio
import json

from app.integrations import llm
from app.pipeline.editor_agent import apply_rules, apply_tool, find_phrase, initial_state, run_editor, to_storyboard
from app.services.captions import CaptionPack


def w(text, start, end):
    return {"text": text, "start": start, "end": end}


WORDS = [
    w("Hey", 0.5, 0.8), w("everyone.", 0.9, 1.3),
    w("Sorry,", 2.0, 2.4), w("let", 2.5, 2.6), w("me", 2.7, 2.8), w("start", 2.9, 3.1), w("again.", 3.2, 3.6),
    w("Three", 4.5, 4.8), w("mistakes", 4.9, 5.4), w("killing", 5.5, 5.9), w("your", 6.0, 6.2), w("reels.", 6.3, 6.8),
    w("Follow", 8.0, 8.3), w("for", 8.4, 8.5), w("more.", 8.6, 9.0),
]
PROBE = {"duration": 10.0, "width": 1920, "height": 1080, "has_audio": True}


def state(**kw):
    return initial_state(None, "clean", len(WORDS), locked=kw.get("locked", False),
                         motion_allowed=kw.get("motion_allowed", False), motion_on=False)


def test_tools_edit_the_storyboard():
    s = state()
    assert apply_tool(s, "remove_words", {"start_word": 2, "end_word": 6, "reason": "restart"}, WORDS, 10).startswith("ok")
    assert apply_tool(s, "set_hook", {"text": "Three mistakes killing your reels today now"}, WORDS, 10).startswith("ok")
    assert apply_tool(s, "highlight_words", {"word_indices": [7, 8, 99]}, WORDS, 10).startswith("error")
    apply_tool(s, "highlight_words", {"word_indices": [7, 8]}, WORDS, 10)
    apply_tool(s, "add_emoji", {"word_index": 8, "emoji": "🔥"}, WORDS, 10)
    assert apply_tool(s, "add_emoji", {"word_index": 8, "emoji": "fire"}, WORDS, 10).startswith("error")
    apply_tool(s, "set_style", {"style": "hype"}, WORDS, 10)
    preview = json.loads(apply_tool(s, "preview_edit", {}, WORDS, 10))
    assert "Sorry" not in preview["kept"] and "Three" in preview["kept"]
    sb = to_storyboard(s, len(WORDS), 10)
    assert sb.style == "hype" and len(sb.hook_text.split()) <= 6 and sb.highlight_word_indices == [7, 8]
    assert sb.emoji_moments[0].emoji == "🔥"


def test_tools_guardrails():
    s = state(locked=True)
    assert apply_tool(s, "set_style", {"style": "funny"}, WORDS, 10).startswith("error")
    assert apply_tool(s, "remove_words", {"start_word": 0, "end_word": 14, "reason": "x"}, WORDS, 10).startswith("error")
    assert apply_tool(s, "set_motion_graphics", {"enabled": True}, WORDS, 10).startswith("error")
    assert apply_tool(state(motion_allowed=True), "set_motion_graphics", {"enabled": True}, WORDS, 10).startswith("ok")
    # a model that sends a JSON array or string as arguments gets an error back instead of crashing the edit
    assert apply_tool(s, "trim", [1, 2], WORDS, 10).startswith("error")
    assert apply_tool(s, "set_look", "hype", WORDS, 10).startswith("error")


def test_rules_handle_common_requests_without_llm():
    s = state()
    trace = apply_rules(s, ["no hook please and captions at the top", "cut the part where I say sorry",
                            "make it cinematic", "no music", "cut the first 2 seconds"], WORDS, 10)
    sb = to_storyboard(s, len(WORDS), 10)
    assert sb.caption_position == "upper" and sb.style == "cinematic" and not sb.music
    assert sb.trim_start_s == 2.0
    assert any(r.start_word == 2 and r.end_word == 6 for r in sb.remove_ranges)
    assert trace


def test_find_phrase_expands_to_sentence():
    assert find_phrase(WORDS, "sorry") == (2, 6)
    assert find_phrase(WORDS, "banana") is None


def test_strict_schema_is_self_contained():
    schema = llm.strict_schema(CaptionPack)
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["options"]["items"]["additionalProperties"] is False


def test_agent_loop_with_scripted_model(monkeypatch):
    """A fake provider that edits through tools, checks its work, then finishes."""
    script = [
        [("remove_words", {"start_word": 2, "end_word": 6, "reason": "restart"}),
         ("set_style", {"style": "hype"}), ("set_hook", {"text": "3 mistakes killing reels"})],
        [("preview_edit", {})],
        [("finish", {"notes": ["Removed the restart"], "scene": "A creator talking to camera"})],
    ]
    calls = iter(script)

    async def fake_chat(provider, messages, **kwargs):
        step = next(calls)
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(step)]}

    monkeypatch.setattr(llm, "providers", lambda: [llm.Provider("fake", "http://x", "k", "m", max_images=0)])
    monkeypatch.setattr(llm, "chat", fake_chat)
    result = asyncio.run(run_editor(frames=[], words=WORDS, probe=PROBE, face_x=None, style_request=None,
                                    user_context=None, brand={}, change_requests=[], previous=None,
                                    motion_requested=False))
    assert result.from_ai and result.editor == "fake"
    assert result.storyboard.style == "hype" and result.storyboard.hook_text == "3 mistakes killing reels"
    assert result.storyboard.edit_notes == ["Removed the restart"]
    assert [t.split("(")[0] for t in result.trace] == ["remove_words", "set_style", "set_hook", "preview_edit", "finish"]


def test_agent_falls_back_to_rules(monkeypatch):
    async def broken_chat(*args, **kwargs):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "providers", lambda: [llm.Provider("fake", "http://x", "k", "m", max_images=0)])
    monkeypatch.setattr(llm, "chat", broken_chat)
    monkeypatch.setattr(llm.claude, "enabled", lambda: False)
    result = asyncio.run(run_editor(frames=[], words=WORDS, probe=PROBE, face_x=None, style_request=None,
                                    user_context=None, brand={}, change_requests=["captions in the middle"],
                                    previous=None, motion_requested=False))
    assert result.editor == "rules" and result.storyboard.caption_position == "middle"


def test_chain_puts_claude_where_configured(monkeypatch):
    groq = llm.Provider("groq", "http://x", "k", "m", max_images=0)
    monkeypatch.setattr(llm, "providers", lambda: [groq])
    monkeypatch.setattr(llm.claude, "enabled", lambda: True)
    monkeypatch.setattr(llm.settings, "llm_providers", "anthropic,groq")
    assert llm.chain() == [None, groq] and llm.names() == ["anthropic", "groq"]
    monkeypatch.setattr(llm.settings, "llm_providers", "groq,anthropic")
    assert llm.chain() == [groq, None]
    monkeypatch.setattr(llm.claude, "enabled", lambda: False)
    assert llm.chain() == [groq]
