"""ASS subtitle track: word-by-word captions, hook title, punchline end card, progress bar."""

from app.pipeline.cuts import Segment, map_span
from app.pipeline.styles import StylePreset

PLAY_W, PLAY_H = 1080, 1920
_ALIGN = {"lower": (2, 430), "middle": (5, 0), "upper": (8, 330)}


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_tag_color(hex_rgb: str) -> str:
    """Colour for inline override tags (\\c&HBBGGRR&)."""
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def clean_text(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def _case(text: str, preset: StylePreset) -> str:
    if preset.uppercase:
        return text.upper()
    if preset.name == "deadpan":
        return text.lower()
    return text


def map_words(words: list[dict], segments: list[Segment], removed: set[int]) -> list[dict]:
    """Words placed on the edited timeline; words that were cut are dropped."""
    out = []
    for i, w in enumerate(words):
        if i in removed:
            continue
        span = map_span(w["start"], w["end"], segments)
        if span:
            out.append({"i": i, "text": clean_text(w["text"]), "start": span[0], "end": span[1]})
    return out


def group_lines(words: list[dict], max_words: int, max_chars: int = 22) -> list[list[dict]]:
    lines: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur and (
            len(cur) >= max_words
            or w["start"] - cur[-1]["end"] > 0.6
            or sum(len(x["text"]) + 1 for x in cur) + len(w["text"]) > max_chars
        ):
            lines.append(cur)
            cur = []
        cur.append(w)
        if w["text"].endswith((".", "!", "?")):
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    return lines


def build_ass(
    *,
    words: list[dict],
    segments: list[Segment],
    removed: set[int],
    preset: StylePreset,
    out_duration: float,
    captions: bool = True,
    caption_position: str = "lower",
    hook_text: str = "",
    punchline_text: str = "",
    cta_text: str = "",
    highlight_indices: set[int] | None = None,
    accent: str | None = None,
) -> str | None:
    highlight_indices = highlight_indices or set()
    hl = ass_color(accent or preset.highlight)
    hl_tag = ass_tag_color(accent or preset.highlight)
    primary = ass_color(preset.primary)
    align, margin_v = _ALIGN.get(caption_position, _ALIGN["lower"])
    fs = preset.font_size
    events: list[str] = []

    punch_start = out_duration
    if punchline_text and out_duration > 4:
        punch_start = max(0.0, out_duration - 2.2)
        body = clean_text(_case(punchline_text, preset))
        if cta_text:
            body += r"\N{\fs" + str(int(fs * 0.5)) + "}" + clean_text(cta_text)
        events.append(
            f"Dialogue: 2,{ass_time(punch_start)},{ass_time(out_duration)},Punch,,0,0,0,,"
            r"{\fad(180,0)\fscx80\fscy80\t(0,220,\fscx100\fscy100)}" + body
        )

    if hook_text:
        events.append(
            f"Dialogue: 3,{ass_time(0)},{ass_time(min(2.6, out_duration))},Hook,,0,0,0,,"
            r"{\fad(120,200)}" + clean_text(_case(hook_text, preset))
        )

    if captions and words:
        mapped = map_words(words, segments, removed)
        lines = group_lines(mapped, preset.words_per_line)
        for j, line in enumerate(lines):
            next_start = lines[j + 1][0]["start"] if j + 1 < len(lines) else out_duration
            line_end = min(line[-1]["end"] + 0.15, next_start, punch_start)
            for k, active in enumerate(line):
                start = active["start"] if k else line[0]["start"]
                end = line[k + 1]["start"] if k + 1 < len(line) else line_end
                if end - start < 0.04 or start >= punch_start:
                    continue
                parts = []
                for w in line:
                    text = _case(w["text"], preset)
                    if w is active:
                        pop = r"\fscx112\fscy112" if preset.pop else ""
                        parts.append("{\\c" + hl_tag + pop + "}" + text + "{\\r}")
                    elif w["i"] in highlight_indices:
                        parts.append("{\\c" + hl_tag + "}" + text + "{\\r}")
                    else:
                        parts.append(text)
                events.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,," + " ".join(parts))

    if preset.progress_bar and out_duration > 2:
        bar = ass_tag_color(preset.highlight)
        dur_ms = int(out_duration * 1000)
        events.append(
            f"Dialogue: 0,{ass_time(0)},{ass_time(out_duration)},Bar,,0,0,0,,"
            r"{\an7\pos(0,0)\c" + bar + r"\clip(0,0,0,14)\t(0," + str(dur_ms) + r",\clip(0,0,1080,14))\p1}"
            "m 0 0 l 1080 0 1080 14 0 14{\\p0}"
        )

    if not events:
        return None

    outline = ass_color(preset.outline)
    shadow = ass_color("#000000", 0x60)
    box = ass_color("#000000", 0x40)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {PLAY_W}
PlayResY: {PLAY_H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{preset.font},{fs},{primary},{hl},{outline},{shadow},0,0,0,0,100,100,1,0,1,{preset.outline_width},2,{align},70,70,{margin_v},1
Style: Hook,{preset.font},{int(fs * 1.1)},{primary},{hl},{box},{box},0,0,0,0,100,100,1,0,3,18,0,8,80,80,240,1
Style: Punch,{preset.font},{int(fs * 1.25)},{ass_color(preset.highlight)},{primary},{outline},{shadow},0,0,0,0,100,100,1,0,1,{preset.outline_width + 2},3,5,80,80,0,1
Style: Bar,{preset.font},20,{ass_color(preset.highlight)},{primary},{outline},{shadow},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header + "\n".join(events) + "\n"
