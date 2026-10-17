"""ASS subtitle track: word-by-word captions, animated hook title, end card, flashes, brand cards, progress bar."""

from app.pipeline.cuts import Segment, map_span
from app.pipeline.genres import LETTERBOX_PX, Recipe
from app.pipeline.styles import StylePreset

PLAY_W, PLAY_H = 1080, 1920
FULL_FRAME = f"m 0 0 l {PLAY_W} 0 {PLAY_W} {PLAY_H} 0 {PLAY_H}"
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


def _wrap(text: str, max_chars: int) -> str:
    """Break a title into lines of at most `max_chars` (WrapStyle 2 never wraps on its own)."""
    lines: list[str] = []
    for word in text.split():
        if lines and len(lines[-1]) + 1 + len(word) <= max_chars:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return r"\N".join(lines)


def _overlay(start: float, end: float, colour: str, alpha_from: int, alpha_to: int, fade_ms: int,
             layer: int = 4) -> str:
    """Full-frame colour wash (white flash on a cut, dimmer behind an end card)."""
    return (f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},Bar,,0,0,0,,"
            r"{\an7\pos(0,0)\bord0\shad0\c" + colour + rf"\alpha&H{alpha_from:02X}&\t(0,{fade_ms},\alpha&H{alpha_to:02X}&)"
            r"\p1}" + FULL_FRAME + r"{\p0}")


def _card(start: float, end: float, text: str, y: int, fs: int, accent_tag: str, layer: int = 3) -> list[str]:
    """Boxed title sliding in from the left with an accent bar on its edge (brand / tutorial look)."""
    x, pad = 120, 22
    n_lines = text.count(r"\N") + 1
    h = int(n_lines * fs * 1.2 + 2 * pad)
    move = rf"\move(-900,{y},{x},{y},0,320)\fad(0,250)"
    bar_move = rf"\move(-938,{y - h // 2},{x - pad - 16},{y - h // 2},0,320)\fad(0,250)"
    return [
        f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},Card,,0,0,0,,{{\\an4{move}\\fs{fs}}}{text}",
        f"Dialogue: {layer + 1},{ass_time(start)},{ass_time(end)},Bar,,0,0,0,,"
        rf"{{\an7{bar_move}\bord0\shad0\c{accent_tag}\p1}}m 0 0 l 16 0 16 {h} 0 {h}{{\p0}}",
    ]


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
    recipe: Recipe | None = None,
    flash_times: list[float] | None = None,
    handle: str = "",
) -> str | None:
    """Captions plus the recipe's graphics: hook animation (slam / sticker / fade / card), white flashes on cuts,
    brand name tag and boxed end card. Without a recipe the hook and end card use the plain look."""
    highlight_indices = highlight_indices or set()
    hl = ass_color(accent or preset.highlight)
    hl_tag = ass_tag_color(accent or preset.highlight)
    primary = ass_color(preset.primary)
    align, margin_v = _ALIGN.get(caption_position, _ALIGN["lower"])
    fs = preset.font_size
    look = recipe.hook if recipe else ""
    cards = bool(recipe and recipe.cards)
    handle = clean_text(handle).lstrip("@")
    events: list[str] = []

    punch_start = out_duration
    if punchline_text and out_duration > 4:
        punch_start = max(0.0, out_duration - 2.2)
        body = clean_text(_case(punchline_text, preset))
        cta = clean_text(cta_text)
        span = f"{ass_time(punch_start)},{ass_time(out_duration)}"
        if look == "fade":  # emotional: the picture dims and the line fades in slowly
            events.append(_overlay(punch_start, out_duration, "&H000000&", 0xFF, 0x70, 700, layer=2))
            body = _wrap(body, 22)
            if cta:
                body += r"\N{\fs" + str(int(fs * 0.55)) + "}" + cta
            events.append(f"Dialogue: 3,{span},Title,,0,0,0,,{{\\an5\\pos(540,900)\\fad(600,0)}}{body}")
        elif cards:  # brand: dimmed frame, headline, CTA in an accent box, handle underneath
            events.append(_overlay(punch_start, out_duration, "&H000000&", 0xFF, 0x60, 300, layer=2))
            events.append(f"Dialogue: 3,{span},Punch,,0,0,0,,"
                          r"{\an5\move(540,880,540,840,0,300)\fad(200,0)}" + _wrap(body, 16))
            if cta:
                events.append(f"Dialogue: 3,{ass_time(punch_start + 0.3)},{ass_time(out_duration)},Cta,,0,0,0,,"
                              r"{\an5\pos(540,1120)\fad(200,0)\fscx80\fscy80\t(0,180,\fscx100\fscy100)}"
                              + _wrap(_case(cta, preset), 26))
            if handle:
                events.append(f"Dialogue: 3,{ass_time(punch_start + 0.5)},{ass_time(out_duration)},Title,,0,0,0,,"
                              r"{\an5\pos(540,1270)\fad(250,0)\fs" + str(int(fs * 0.5)) + "}@" + handle)
        else:
            body = _wrap(body, 16)
            if cta:
                body += r"\N{\fs" + str(int(fs * 0.5)) + "}" + cta
            if look == "slam":
                anim = r"{\fscx165\fscy165\t(0,160,\fscx100\fscy100)}"
                events.append(_overlay(punch_start, punch_start + 0.2, "&HFFFFFF&", 0x50, 0xFF, 200))
            elif look == "sticker":
                anim = r"{\fad(120,0)\frz-3\fscx60\fscy60\t(0,180,\fscx108\fscy108)\t(180,280,\fscx100\fscy100)}"
            else:
                anim = r"{\fad(180,0)\fscx80\fscy80\t(0,220,\fscx100\fscy100)}"
            events.append(f"Dialogue: 2,{span},Punch,,0,0,0,," + anim + body)

    if hook_text:
        hook = clean_text(_case(hook_text, preset))
        hook_end = min(2.6, out_duration)
        if look == "slam":
            events.append(_overlay(0, 0.22, "&HFFFFFF&", 0x50, 0xFF, 220))
            events.append(f"Dialogue: 3,{ass_time(0)},{ass_time(hook_end)},Hook,,0,0,0,,"
                          r"{\fad(0,200)\fscx175\fscy175\t(0,170,\fscx100\fscy100)\t(170,230,\frz2)"
                          r"\t(230,290,\frz-1.5)\t(290,350,\frz0)}" + _wrap(hook, 18))
        elif look == "sticker":
            events.append(f"Dialogue: 3,{ass_time(0)},{ass_time(hook_end)},Sticker,,0,0,0,,"
                          r"{\fad(60,200)\frz-3\fscx40\fscy40\t(0,150,\fscx112\fscy112)\t(150,260,\fscx100\fscy100)}"
                          + _wrap(hook, 18))
        elif look == "fade":
            hook_end = min(3.2, out_duration)
            events.append(f"Dialogue: 3,{ass_time(0)},{ass_time(hook_end)},Title,,0,0,0,,"
                          r"{\an5\pos(540,700)\fad(700,600)\fsp14\t(0,3000,\fsp4)}" + _wrap(hook, 22))
        elif look == "card":
            events += _card(0, hook_end, _wrap(hook, 18), 360, int(fs * 0.95), hl_tag)
        else:
            events.append(f"Dialogue: 3,{ass_time(0)},{ass_time(hook_end)},Hook,,0,0,0,,"
                          r"{\fad(120,200)}" + _wrap(hook, 18))

    if cards and handle and punch_start - 2.9 > 3:  # name tag after the title card
        events += _card(2.9, min(6.4, punch_start - 0.3), "@" + handle, 360, int(fs * 0.55), hl_tag)

    if recipe and recipe.flash_cuts:
        last = -9.0
        for t in sorted(flash_times or []):
            if 0.3 < t < punch_start - 0.3 and t - last >= 1.5:  # no strobing on rapid cuts
                events.append(_overlay(t, t + 0.16, "&HFFFFFF&", 0x78, 0xFF, 160))
                last = t

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
        top = LETTERBOX_PX if recipe and recipe.letterbox else 0
        dur_ms = int(out_duration * 1000)
        events.append(
            f"Dialogue: 0,{ass_time(0)},{ass_time(out_duration)},Bar,,0,0,0,,"
            rf"{{\an7\pos(0,{top})\c" + bar + rf"\clip(0,{top},0,{top + 14})\t(0," + str(dur_ms)
            + rf",\clip(0,{top},1080,{top + 14}))\p1}}"
            "m 0 0 l 1080 0 1080 14 0 14{\\p0}"
        )

    if not events:
        return None

    outline = ass_color(preset.outline)
    shadow = ass_color("#000000", 0x60)
    box = ass_color("#000000", 0x40)
    card_box = ass_color("#0D0D0D", 0x18)
    dark = ass_color("#111111")
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
Style: Sticker,{preset.font},{int(fs * 0.95)},{dark},{hl},{hl},{hl},0,0,0,0,100,100,1,0,3,20,0,8,80,80,250,1
Style: Title,{preset.font},{int(fs * 0.9)},{primary},{hl},{outline},{shadow},0,0,0,0,100,100,2,0,1,2,3,5,80,80,0,1
Style: Card,{preset.font},{int(fs * 0.8)},{ass_color("#FFFFFF")},{hl},{card_box},{card_box},0,0,0,0,100,100,1,0,3,22,0,4,80,80,0,1
Style: Cta,{preset.font},{int(fs * 0.62)},{dark},{hl},{hl},{hl},0,0,0,0,100,100,1,0,3,22,0,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return header + "\n".join(events) + "\n"
