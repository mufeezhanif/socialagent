from dataclasses import dataclass

STYLE_ORDER = ["clean", "hype", "cinematic", "funny", "deadpan", "luxury"]


@dataclass(frozen=True)
class StylePreset:
    name: str
    label: str
    description: str
    font: str
    font_size: int
    uppercase: bool
    words_per_line: int
    primary: str  # caption text colour, #RRGGBB
    highlight: str  # active word colour
    outline: str
    outline_width: int
    grade: str  # ffmpeg filter chain applied to the whole edit
    zoom_alternate: bool  # punch in on every other cut to hide jump cuts
    progress_bar: bool
    pop: bool  # active word pops (scale)


PRESETS: dict[str, StylePreset] = {
    "clean": StylePreset(
        "clean", "Clean", "simple, readable, natural colour",
        "Anton", 86, False, 3, "#FFFFFF", "#FFD400", "#000000", 5,
        "eq=contrast=1.03:saturation=1.06", False, False, False,
    ),
    "hype": StylePreset(
        "hype", "Hype", "punchy zoom cuts, bold colour, progress bar",
        "Anton", 108, True, 2, "#FFFFFF", "#39FF14", "#000000", 7,
        "eq=contrast=1.10:saturation=1.30:brightness=0.01,unsharp=5:5:0.6", True, True, True,
    ),
    "cinematic": StylePreset(
        "cinematic", "Cinematic", "moody grade, calm captions",
        "Anton", 70, False, 4, "#F5F1E8", "#E8B86D", "#101010", 3,
        "eq=contrast=1.08:saturation=0.82,colorbalance=rs=0.04:gs=0.01:bs=-0.05,vignette=PI/5", False, False, False,
    ),
    "funny": StylePreset(
        "funny", "Funny", "loud colours, popping words",
        "Anton", 110, True, 2, "#FFFFFF", "#FF3EA5", "#000000", 8,
        "eq=contrast=1.06:saturation=1.40", True, True, True,
    ),
    "deadpan": StylePreset(
        "deadpan", "Deadpan", "flat and dry, lowercase captions",
        "Anton", 72, False, 4, "#FFFFFF", "#FFFFFF", "#000000", 4,
        "eq=contrast=1.00:saturation=0.75", False, False, False,
    ),
    "luxury": StylePreset(
        "luxury", "Luxury", "warm, elegant, gold accents",
        "Anton", 74, True, 3, "#FFFDF7", "#D4AF37", "#1A1408", 3,
        "eq=contrast=1.05:saturation=0.92,colorbalance=rs=0.05:gs=0.02:bs=-0.04,vignette=PI/6", False, False, False,
    ),
}


def get_preset(name: str | None) -> StylePreset:
    return PRESETS.get((name or "clean").lower(), PRESETS["clean"])


def next_style(current: str, tried: list[str] | None = None) -> str:
    tried = tried or []
    start = STYLE_ORDER.index(current) if current in STYLE_ORDER else 0
    for i in range(1, len(STYLE_ORDER) + 1):
        candidate = STYLE_ORDER[(start + i) % len(STYLE_ORDER)]
        if candidate not in tried:
            return candidate
    return STYLE_ORDER[(start + 1) % len(STYLE_ORDER)]
