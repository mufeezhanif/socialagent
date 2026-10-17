"""The director's output contract. Claude fills it; code validates and clamps it before anything renders."""

from typing import Literal

from pydantic import BaseModel, Field

from app.pipeline.styles import PRESETS

Style = Literal["clean", "hype", "cinematic", "funny", "deadpan", "luxury"]
VideoType = Literal["vlog", "energetic", "emotional", "brand", "tutorial", "funny"]


class RemoveRange(BaseModel):
    start_word: int = Field(description="Index of the first word to remove (inclusive)")
    end_word: int = Field(description="Index of the last word to remove (inclusive)")
    reason: str = Field(description="Short reason shown to the user, e.g. 'false start'")


class EmojiMoment(BaseModel):
    word_index: int = Field(description="Word index where the emoji pops in")
    emoji: str = Field(description="A single emoji")


class Storyboard(BaseModel):
    style: Style
    video_type: VideoType = Field("vlog", description="Kind of video; picks the music, sound effects and graphics")
    hook_text: str = Field(description="On-screen hook for the first ~2.5 s, max 6 words, empty for none")
    remove_ranges: list[RemoveRange] = Field(description="Word ranges to cut: false starts, repeats, apologies, off-topic")
    highlight_word_indices: list[int] = Field(description="Up to 8 word indices to emphasise in captions")
    emoji_moments: list[EmojiMoment] = Field(description="Up to 4 emoji pops on key words; empty for serious content")
    punchline_text: str = Field(description="End-card line for the last ~2 s, max 7 words, empty for none")
    cta_text: str = Field(description="Small call to action under the punchline, empty for none")
    crop_mode: Literal["auto", "blur_pad", "crop"]
    captions_enabled: bool
    caption_position: Literal["lower", "middle", "upper"]
    trim_start_s: float = Field(description="Extra seconds to cut from the very start, usually 0")
    trim_end_s: float = Field(description="Extra seconds to cut from the very end, usually 0")
    music: bool = Field(description="Add a soft music bed under the voice")
    scene_description: str = Field(description="One or two sentences on what the video shows, for caption writing")
    edit_notes: list[str] = Field(description="Up to 3 short notes for the user about judgement calls you made")
    question_for_user: str = Field(description="Ask instead of guessing when something important is unclear; empty otherwise")


def _clip_words(text: str, max_words: int, max_chars: int) -> str:
    words = text.strip().split()
    return " ".join(words[:max_words])[:max_chars].strip()


def validate_storyboard(sb: Storyboard, n_words: int, duration: float, max_cut: float = 0.6) -> Storyboard:
    """max_cut: largest share of the spoken words that may be removed (raised only for an explicit target length)."""
    data = sb.model_dump()
    if data["style"] not in PRESETS:
        data["style"] = "clean"
    data["hook_text"] = _clip_words(data["hook_text"], 6, 40)
    data["punchline_text"] = _clip_words(data["punchline_text"], 7, 48)
    data["cta_text"] = _clip_words(data["cta_text"], 8, 48)

    ranges = []
    removed_count = 0
    for r in data["remove_ranges"]:
        start, end = sorted((int(r["start_word"]), int(r["end_word"])))
        start, end = max(0, start), min(n_words - 1, end)
        if n_words == 0 or start > end:
            continue
        removed_count += end - start + 1
        ranges.append({"start_word": start, "end_word": end, "reason": r["reason"][:80]})
    # Never let the director delete most of the speech.
    if n_words and removed_count > n_words * max_cut:
        ranges = []
    data["remove_ranges"] = ranges

    data["highlight_word_indices"] = sorted({i for i in data["highlight_word_indices"] if 0 <= i < n_words})[:8]
    data["emoji_moments"] = [
        m for m in data["emoji_moments"]
        if 0 <= int(m["word_index"]) < n_words and 0 < len(m["emoji"].strip()) <= 6
    ][:4]
    max_trim = max(0.0, duration / 3)
    data["trim_start_s"] = min(max(0.0, float(data["trim_start_s"])), max_trim)
    data["trim_end_s"] = min(max(0.0, float(data["trim_end_s"])), max_trim)
    if n_words == 0:
        data["captions_enabled"] = False
    data["scene_description"] = data["scene_description"][:400]
    data["edit_notes"] = [n[:120] for n in data["edit_notes"][:3]]
    data["question_for_user"] = data["question_for_user"][:200]
    return Storyboard.model_validate(data)


def fallback_storyboard(style: str, n_words: int, video_type: str = "vlog") -> Storyboard:
    return Storyboard(
        style=style if style in PRESETS else "clean",
        video_type=video_type,
        hook_text="",
        remove_ranges=[],
        highlight_word_indices=[],
        emoji_moments=[],
        punchline_text="",
        cta_text="",
        crop_mode="auto",
        captions_enabled=n_words > 0,
        caption_position="lower",
        trim_start_s=0.0,
        trim_end_s=0.0,
        music=False,
        scene_description="",
        edit_notes=[],
        question_for_user="",
    )


def removed_word_set(sb: Storyboard) -> set[int]:
    removed: set[int] = set()
    for r in sb.remove_ranges:
        removed.update(range(r.start_word, r.end_word + 1))
    return removed
