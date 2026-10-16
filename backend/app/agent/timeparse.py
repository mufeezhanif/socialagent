"""Deterministic parsing for the common ways people say a time. Claude handles the rest."""

import re
from datetime import datetime, timedelta

_REL = re.compile(r"\bin\s+(\d+(?:\.\d+)?)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours)\b")
_CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b")


def parse_time(text: str, now_local: datetime) -> datetime | None:
    """Returns an aware datetime in now_local's timezone, or None if not understood."""
    t = text.lower().strip()
    if t in {"now", "right now", "asap"}:
        return now_local + timedelta(seconds=5)

    m = _REL.search(t)
    if m:
        amount = float(m.group(1))
        minutes = amount if m.group(2).startswith("m") else amount * 60
        return now_local + timedelta(minutes=minutes)

    day_offset = None
    if "tomorrow" in t:
        day_offset = 1
    elif any(w in t for w in ("today", "tonight", "this evening")):
        day_offset = 0

    clock = None
    for cm in _CLOCK.finditer(t):
        hour, minute, ampm = int(cm.group(1)), int(cm.group(2) or 0), cm.group(3)
        if ampm is None and cm.group(2) is None:
            continue  # bare number like "2" is too ambiguous
        if hour > 23 or minute > 59:
            continue
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        clock = (hour, minute)
        break
    if clock is None:
        if "tonight" in t:
            clock = (20, 0)
        elif day_offset is not None and "morning" in t:
            clock = (9, 0)
        elif day_offset is not None and "evening" in t:
            clock = (19, 0)
        else:
            return None

    base = now_local.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
    if day_offset is None:
        return base if base > now_local else base + timedelta(days=1)
    return base + timedelta(days=day_offset)


def suggest_slot(now_local: datetime, preferred: str = "19:00") -> datetime:
    try:
        hour, minute = (int(x) for x in preferred.split(":"))
    except ValueError:
        hour, minute = 19, 0
    slot = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return slot if slot > now_local + timedelta(minutes=10) else slot + timedelta(days=1)


def human_time(dt: datetime) -> str:
    return dt.strftime("%a %d %b, %I:%M %p").replace(" 0", " ") + f" {dt.tzname() or ''}".rstrip()
