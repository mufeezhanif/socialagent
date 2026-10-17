import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.agent import intents
from app.agent.timeparse import parse_time
from app.services.captions import CaptionOption, CaptionPack, full_caption, validate_pack
from app.services.publisher import GateError, check_gates

NOW = datetime(2026, 10, 17, 1, 50, tzinfo=ZoneInfo("Asia/Karachi"))


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "text,expected",
    [("1", "approve"), ("👍", "approve"), ("Looks good!", "approve"), ("4", "discard"), ("3", "style"),
     ("make it cinematic", "style"), ("2", "change"), ("👍🏽", "approve"), ("Awesome!", "approve")],
)
def test_approval_quick_intents(text, expected):
    assert run(intents.approval(text)).name == expected


def test_skin_tone_reactions_count_as_likes():
    assert intents.is_like("👍🏻") and intents.is_like("❤️") and not intents.is_like("😢") and not intents.is_like(None)


def test_change_with_inline_notes():
    intent = run(intents.approval("2 cut the intro"))
    assert intent.name == "change" and intent.data["notes"] == "cut the intro"


def test_publish_choice():
    assert intents.publish_choice("1").name == "now"
    assert intents.publish_choice("schedule tomorrow 7pm").data == {"when": "tomorrow 7pm"}
    assert intents.publish_choice("3").name == "save"


def test_time_parsing():
    assert parse_time("in 2 minutes", NOW).minute == 52
    assert parse_time("tomorrow 9am", NOW).day == 18
    assert parse_time("today 8pm", NOW).hour == 20
    assert parse_time("blah", NOW) is None
    assert parse_time("tonight at 9", NOW).hour == 21 and parse_time("tomorrow morning 10", NOW).hour == 10
    assert parse_time("in an hour", NOW).hour == 2


def test_caption_pack_limits():
    pack = CaptionPack(
        options=[CaptionOption(style="hook", text="Big news 🎉 buy now")],
        hashtags=["#Reels", "reels", "My Tag!", "spam"] + [f"t{i}" for i in range(30)],
        facts_to_confirm=[],
    )
    out = validate_pack(pack, {"default_hashtags": ["brand"], "banned_words": ["buy now", "spam"]})
    assert len(out["options"]) == 3
    assert "buy now" not in out["options"][0]["text"].lower()
    assert out["hashtags"][0] == "brand" and "spam" not in out["hashtags"]
    assert len(out["hashtags"]) <= 15 and len(set(out["hashtags"])) == len(out["hashtags"])
    assert len(full_caption("x" * 3000, out["hashtags"])) <= 2200


def draft(**kw):
    base = dict(revision=2, video_approved_rev=2, caption_approved_at=NOW, caption_final="hi",
                publish_confirmed_at=NOW, master_path="m.mp4")
    base.update(kw)
    return SimpleNamespace(**base)


def test_gates_block_unapproved_publishing():
    check_gates(draft())
    for bad in (dict(video_approved_rev=1), dict(video_approved_rev=None), dict(caption_approved_at=None),
                dict(publish_confirmed_at=None), dict(master_path=None)):
        with pytest.raises(GateError):
            check_gates(draft(**bad))


def test_gate_requires_current_revision():
    # approving revision 1 and then asking for changes must not let revision 2 publish
    with pytest.raises(GateError):
        check_gates(draft(revision=2, video_approved_rev=1))
    assert datetime.now(timezone.utc)
