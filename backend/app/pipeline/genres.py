"""Video types and their edit recipes: music mood, sound effects, look and on-screen graphics.

The editor (LLM or keyword rules) decides what kind of video it is; the recipe turns that into concrete render
choices, so an energetic clip gets beat music, whooshes and flash cuts while an emotional one gets a soft score,
letterbox bars, grain and slow fades, and a brand video gets title cards and a clean end card.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.pipeline.cuts import Segment, normalize_word

VIDEO_TYPES = ["vlog", "energetic", "emotional", "brand", "tutorial", "funny"]
LETTERBOX_PX = 150  # cinematic bars, top and bottom


@dataclass(frozen=True)
class Recipe:
    name: str
    description: str  # shown to the editor LLM
    style: str  # default style preset
    music: str | None  # assets/music/<name>.* (None: no music bed by default)
    music_volume: float
    hook: str  # hook animation: slam | sticker | fade | card
    flash_cuts: bool  # white flash on real cuts
    letterbox: bool
    grain: bool
    fades: bool  # fade in from / out to black
    drift: bool  # slow camera float
    cards: bool  # brand title card, name tag and boxed end card
    emoji: bool  # emoji pops suit the tone


RECIPES: dict[str, Recipe] = {
    "vlog": Recipe("vlog", "day-in-the-life, travel, personal updates", "clean", "clean", 0.18,
                   "sticker", False, False, False, False, False, False, True),
    "energetic": Recipe("energetic", "events, sport, gym, hype, celebrations", "hype", "hype", 0.26,
                        "slam", True, False, False, False, False, False, True),
    "emotional": Recipe("emotional", "heartfelt, sad, gratitude, personal stories, tributes", "cinematic",
                        "emotional", 0.2, "fade", False, True, True, True, True, False, False),
    "brand": Recipe("brand", "product, business, promo, launch, announcement", "luxury", "luxury", 0.18,
                    "card", False, False, False, True, True, True, False),
    "tutorial": Recipe("tutorial", "how-to, tips, explainers, reviews", "clean", "clean", 0.12,
                       "card", False, False, False, False, False, False, False),
    "funny": Recipe("funny", "comedy, skits, pranks, memes", "funny", "funny", 0.22,
                    "sticker", True, False, False, False, False, False, True),
}

LOOK_SUMMARY = {  # one line for the user's edit summary
    "vlog": "sticker hook, light pops and swooshes",
    "energetic": "slam-in hook, flash cuts, whooshes and impacts",
    "emotional": "cinematic bars, film grain, slow fades and a soft swell",
    "brand": "title card, name tag and a clean end card",
    "tutorial": "title card and a ding on each key point",
    "funny": "sticker hook, flash cuts and pops",
}
MUSIC_LABEL = {"hype": "Upbeat", "emotional": "Emotional piano", "luxury": "Elegant", "funny": "Playful",
               "clean": "Soft"}


def get_recipe(name: str | None) -> Recipe:
    return RECIPES.get((name or "vlog").lower(), RECIPES["vlog"])


def find_track(name: str | None) -> Path | None:
    """Music bed assets/music/<name>.(mp3|m4a|wav|ogg)."""
    music_dir = Path(settings.assets_dir) / "music"
    if not name or not music_dir.is_dir():
        return None
    for candidate in sorted(music_dir.glob(f"{name}.*")):
        if candidate.suffix.lower() in {".mp3", ".m4a", ".wav", ".ogg"}:
            return candidate
    return None


def sfx_file(name: str) -> Path | None:
    path = Path(settings.assets_dir) / "sfx" / f"{name}.wav"
    return path if path.exists() else None


# ------------------------------------------------------------------ classification without an LLM

_KEYWORDS = {
    "energetic": ("let's go", "lets go", "event", "fest", "festival", "match", "game", "gym", "workout", "competition",
                  "concert", "party", "hype", "crazy", "insane", "win", "won", "championship", "race", "dance",
                  "celebrate", "celebration", "launch day", "crowd", "stage"),
    "emotional": ("miss you", "i miss", "grateful", "thank you so much", "passed away", "lost my", "tears", "cry",
                  "cried", "memories", "remember when", "journey", "heart", "love you", "sad", "hard time",
                  "struggle", "goodbye", "tribute", "mom", "mother", "father", "dad", "grandma", "grandpa"),
    "brand": ("buy", "order now", "order", "discount", "offer", "sale", "product", "our brand", "available",
              "shop", "store", "price", "customers", "link in bio", "dm us", "book now", "delivery", "launching",
              "new collection", "service", "business", "company", "website"),
    "tutorial": ("how to", "step one", "step 1", "first step", "tip", "tips", "here's how", "heres how", "learn",
                 "tutorial", "guide", "explain", "review", "recipe", "you need", "make sure"),
    "funny": ("lol", "haha", "joke", "prank", "funny", "meme", "bro what", "plot twist", "pov"),
}
_TYPE_WORDS = {
    "energetic": r"energetic|hype|high energy|exciting|event|sports?|gym",
    "emotional": r"emotional|sad|heartfelt|sentimental|touching|cinematic|tribute",
    "brand": r"brand|promo|promotional|product|ad|advert|business|commercial|professional|corporate",
    "tutorial": r"tutorial|how-?to|explainer|educational|tips?",
    "funny": r"funny|comedy|skit|meme|prank",
    "vlog": r"vlog|daily|day in (?:my|the) life",
}


def type_from_request(text: str) -> str | None:
    """'make it more energetic', 'this is a brand promo' -> the video type the user names, if any."""
    t = (text or "").lower()
    for name, pattern in _TYPE_WORDS.items():
        if re.search(rf"\b(?:{pattern})\b", t):
            return name
    return None


def classify(words: list[dict], notes: str | None = None, brand: dict | None = None) -> str:
    """Keyword guess at the video type from the user's note (strongest), the transcript and the brand kit."""
    named = type_from_request(notes or "")
    if named:
        return named
    text = " " + " ".join(normalize_word(w["text"]) for w in words) + " "
    extra = " " + " ".join(normalize_word(x) for x in f"{notes or ''} {(brand or {}).get('niche') or ''}".split()) + " "
    scores = {}
    for name, keys in _KEYWORDS.items():
        scores[name] = sum(text.count(f" {k} ") + 2 * extra.count(f" {k} ") for k in keys)
    best = max(scores, key=scores.get)
    if scores[best] >= 2:
        return best
    seconds = (words[-1]["end"] - words[0]["start"]) if words else 0
    if words and len(words) / max(seconds, 1) > 3.3:  # fast talkers read as energetic
        return "energetic"
    return "vlog"


# ------------------------------------------------------------------ timing of sound effects and flashes

def cut_points(segments: list[Segment], out_duration: float, min_skip: float = 0.8, spacing: float = 2.5,
               limit: int = 6) -> list[float]:
    """Output times of real cuts (where at least `min_skip` seconds of source were removed), spaced out."""
    points, t, last = [], 0.0, -spacing
    for k, (s, e) in enumerate(segments):
        if k and s - segments[k - 1][1] >= min_skip and 0.6 < t < out_duration - 2.6 and t - last >= spacing:
            points.append(round(t, 3))
            last = t
        t += e - s
    return points[:limit]


def _spaced(times: list[float], spacing: float, limit: int) -> list[float]:
    out: list[float] = []
    for t in sorted(times):
        if not out or t - out[-1] >= spacing:
            out.append(t)
    return out[:limit]


def plan_sfx(recipe: Recipe, *, cuts: list[float], highlights: list[float], emojis: list[float], out_duration: float,
             hook: bool, punch_start: float | None) -> list[tuple[float, str, float]]:
    """(output seconds, sound name, volume) for the recipe. Quiet, few and on the beat of the edit."""
    events: list[tuple[float, str, float]] = []
    end = punch_start if punch_start is not None else out_duration
    if recipe.name == "energetic":
        if hook:
            events.append((0.0, "impact", 0.5))
        events += [(t - 0.25, "whoosh", 0.35) for t in _spaced(cuts, 1.5, 10)]  # one per cut, not a wall of noise
        if punch_start is not None and punch_start > 3:
            events += [(punch_start - 1.4, "riser", 0.3), (punch_start, "impact", 0.45)]
    elif recipe.name == "funny":
        events += [(t, "pop", 0.4) for t in _spaced(emojis + highlights, 1.5, 6)]
        events += [(t - 0.25, "whoosh", 0.25) for t in cuts[:3]]
    elif recipe.name == "vlog":
        events += [(t, "pop", 0.3) for t in _spaced(emojis or highlights, 2.0, 4)]
        events += [(t - 0.25, "whoosh", 0.2) for t in cuts[:3]]
    elif recipe.name == "tutorial":
        events += [(t, "ding", 0.25) for t in _spaced(highlights, 2.5, 4)]
    elif recipe.name == "brand":
        events.append((0.0, "whoosh", 0.3))
        if punch_start is not None:
            events.append((max(0.0, punch_start - 0.2), "whoosh", 0.3))
    elif recipe.name == "emotional":
        events.append((0.0, "swell", 0.3))
        if punch_start is not None and punch_start > 4:
            events.append((max(0.0, punch_start - 1.0), "swell", 0.25))
    return [(round(max(0.0, t), 3), name, vol) for t, name, vol in events if t < end + 0.5 and t < out_duration - 0.2]
