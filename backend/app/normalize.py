"""Slot normalisers and matchers (PROJECT.md §3.1). Pure functions, no I/O.

Slot types: person, place, day, time, number, code_word.
`normalize_slot` gives a canonical value (or None if unparseable);
`slot_matches` decides whether a heard value equals a card target.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from .config import Settings, settings as default_settings

SlotType = Literal["person", "place", "day", "time", "number", "code_word"]

# ---------------------------------------------------------------------------
# Tokens and number words
# ---------------------------------------------------------------------------

_DIGITS = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUMBER_WORDS = set(_DIGITS) | set(_TEENS) | set(_TENS) | {"hundred"}


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens; keeps digits, ':' inside times and apostrophes inside words."""
    text = text.lower().replace("o'clock", "oclock")
    text = re.sub(r"(\d)[.:](\d)", r"\1:\2", text)  # 4.30 -> 4:30
    text = re.sub(r"(\d),(\d{3})\b", r"\1\2", text)  # 1,500 -> 1500
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)  # 4pm -> 4 pm, gate15 -> gate 15
    return re.findall(r"[a-z0-9:]+(?:'[a-z]+)?", text)


def _parse_number_phrase(tokens: list[str], i: int) -> tuple[str, int] | None:
    """Parse one spoken number starting at tokens[i]. Returns (digits, next_index).

    Grammar: a run of 2+ single digits is a digit string ("one five" -> "15",
    "four oh five" -> "405"); otherwise [unit hundred [and]] [teen | unit | tens [unit]].
    "oh" only counts as zero inside a digit run.
    """
    n = len(tokens)
    # Digit string: two or more single-digit words in a row.
    j = i
    while j < n and tokens[j] in _DIGITS and not (j == i and tokens[j] == "oh"):
        j += 1
    if j - i >= 2:
        return "".join(str(_DIGITS[t]) for t in tokens[i:j]), j

    value, j, matched = 0, i, False
    if j + 1 < n and tokens[j] in _DIGITS and tokens[j] != "oh" and tokens[j + 1] == "hundred":
        value, j, matched = _DIGITS[tokens[j]] * 100, j + 2, True
        if j < n and tokens[j] == "and" and j + 1 < n and tokens[j + 1] in _NUMBER_WORDS - {"hundred", "oh"}:
            j += 1
    if j < n and tokens[j] in _TEENS:
        return str(value + _TEENS[tokens[j]]), j + 1
    if j < n and tokens[j] in _TENS:
        value += _TENS[tokens[j]]
        j += 1
        if j < n and tokens[j] in _DIGITS and tokens[j] not in ("zero", "oh"):
            value += _DIGITS[tokens[j]]
            j += 1
        return str(value), j
    if j < n and tokens[j] in _DIGITS and tokens[j] != "oh":
        return str(value + _DIGITS[tokens[j]]), j + 1
    return (str(value), j) if matched else None


def numbers_to_digits(tokens: list[str]) -> list[str]:
    """Replace spoken numbers with digit strings: ['gate', 'fifteen'] -> ['gate', '15']."""
    out, i = [], 0
    while i < len(tokens):
        parsed = _parse_number_phrase(tokens, i)
        if parsed is None:
            out.append(tokens[i])
            i += 1
        else:
            out.append(parsed[0])
            i = parsed[1]
    return out


# ---------------------------------------------------------------------------
# Per-type normalisers
# ---------------------------------------------------------------------------


def normalize_person(text: str) -> str | None:
    words = re.findall(r"[^\W\d_]+(?:['-][^\W\d_]+)*", text)
    return " ".join(w.capitalize() for w in words) or None


def person_matches(heard: str, target: str, s: Settings = default_settings) -> bool:
    a, b = normalize_person(heard), normalize_person(target)
    if a is None or b is None:
        return False
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= s.person_fuzzy_threshold


_PLACE_STOPWORDS = {"at", "the", "to", "in", "on", "by"}


def normalize_place(text: str) -> str | None:
    """'at gate fifteen' -> 'Gate 15'; digits are normalised, leading prepositions dropped."""
    tokens = numbers_to_digits(tokenize(text))
    while tokens and tokens[0] in _PLACE_STOPWORDS:
        tokens = tokens[1:]
    return " ".join(t if t[0].isdigit() else t.capitalize() for t in tokens) or None


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAY_ALIASES = {
    "mon": "monday",
    "tue": "tuesday", "tues": "tuesday",
    "wed": "wednesday", "weds": "wednesday",
    "thu": "thursday", "thur": "thursday", "thurs": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "sun": "sunday",
}  # fmt: skip


def normalize_day(text: str) -> str | None:
    """Weekday enum as a lowercase name; None if no (or more than one) weekday is mentioned."""
    found = set()
    for t in tokenize(text):
        t = t.removesuffix("'s")
        if t.endswith("s") and t[:-1] in _WEEKDAYS:  # "thursdays"
            t = t[:-1]
        if t in _WEEKDAYS:
            found.add(t)
        elif t in _DAY_ALIASES:
            found.add(_DAY_ALIASES[t])
    return found.pop() if len(found) == 1 else None


@dataclass(frozen=True)
class NormalizedTime:
    hour: int  # 0-23
    minute: int
    # False when no am/pm (or 24-hour clue) was given, e.g. "four thirty".
    explicit: bool

    @property
    def hhmm(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


_AM = {"am", "morning"}
_PM = {"pm", "afternoon", "evening", "night", "tonight"}


def normalize_time(text: str) -> NormalizedTime | None:
    """Parse '4:30', '16:30', 'half past four', 'four thirty pm', 'quarter to five',
    'four o'clock', '4 pm', 'noon' into a time. Ambiguous (no am/pm) times keep
    the hour as spoken (1-12) and explicit=False."""
    raw = tokenize(text.replace("a.m.", "am").replace("p.m.", "pm"))
    raw = [t for t in raw if t not in ("minutes", "minute")]
    if "noon" in raw or "midday" in raw:
        return NormalizedTime(12, 0, True)
    if "midnight" in raw:
        return NormalizedTime(0, 0, True)
    meridiem = "am" if _AM & set(raw) else "pm" if _PM & set(raw) else None
    tokens = numbers_to_digits(raw)
    s = " ".join(tokens)

    hour = minute = None
    zero_padded = False  # "09:15" is written 24-hour style
    if m := re.search(r"\bhalf past (\d{1,2})\b", s):
        hour, minute = int(m[1]), 30
    elif m := re.search(r"\bquarter past (\d{1,2})\b", s):
        hour, minute = int(m[1]), 15
    elif m := re.search(r"\bquarter to (\d{1,2})\b", s):
        hour, minute = int(m[1]) - 1, 45
    elif m := re.search(r"\b(\d{1,2}) past (\d{1,2})\b", s):
        hour, minute = int(m[2]), int(m[1])
    elif m := re.search(r"\b(\d{1,2}) to (\d{1,2})\b", s):
        hour, minute = int(m[2]) - 1, 60 - int(m[1])
    elif m := re.search(r"\b(\d{1,2}):(\d{2})\b", s):
        hour, minute = int(m[1]), int(m[2])
        zero_padded = len(m[1]) == 2 and m[1][0] == "0"
    elif m := re.search(r"\b(\d{1,2}) (\d{2})\b", s):  # "four thirty" -> "4 30"
        hour, minute = int(m[1]), int(m[2])
    elif m := re.search(r"\b(\d{1,2})(\d{2})\b", s):  # "1630", "four oh five" -> "405"
        hour, minute = int(m[1]), int(m[2])
    elif m := re.search(r"\b(\d{1,2})(?: oclock| am| pm)\b", s):
        hour, minute = int(m[1]), 0
    elif meridiem and (m := re.fullmatch(r"(?:at )?(\d{1,2})(?: in the \w+)?(?: am| pm)?", s)):
        hour, minute = int(m[1]), 0
    elif m := re.fullmatch(r"(?:at )?(\d{1,2})", s):  # bare hour: "four"
        hour, minute = int(m[1]), 0
    if hour is None or minute is None:
        return None
    if hour == 0 and meridiem is None and "to" in tokens:  # "quarter to one" -> 12:45
        hour = 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if meridiem and 1 <= hour <= 12:
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return NormalizedTime(hour, minute, True)
    # 0:xx and 13:00-23:59 are unambiguous 24-hour times.
    return NormalizedTime(hour, minute, zero_padded or hour == 0 or hour > 12)


def time_matches(heard: str, target: str) -> bool:
    """'4:30' matches a 16:30 target (no am/pm said); '4:30 am' does not."""
    h, t = normalize_time(heard), normalize_time(target)
    if h is None or t is None:
        return False
    if h.explicit and t.explicit:
        return (h.hour, h.minute) == (t.hour, t.minute)
    return (h.hour % 12, h.minute) == (t.hour % 12, t.minute)


def normalize_number(text: str) -> int | None:
    digits = [t for t in numbers_to_digits(tokenize(text)) if t.isdigit()]
    return int(digits[0]) if len(digits) == 1 else None


def normalize_code_word(text: str) -> str | None:
    """Exact after lowercasing; punctuation and spaces removed ('BAT.' -> 'bat')."""
    return re.sub(r"[^a-z]", "", text.lower()) or None


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def normalize_slot(slot_type: SlotType, value: str | None) -> str | None:
    """Canonical string for display/storage; None if empty or unparseable."""
    if value is None or not value.strip():
        return None
    if slot_type == "person":
        return normalize_person(value)
    if slot_type == "place":
        return normalize_place(value)
    if slot_type == "day":
        return normalize_day(value)
    if slot_type == "time":
        t = normalize_time(value)
        return t.hhmm if t else None
    if slot_type == "number":
        n = normalize_number(value)
        return str(n) if n is not None else None
    if slot_type == "code_word":
        return normalize_code_word(value)
    raise ValueError(f"unknown slot type: {slot_type}")


def slot_matches(slot_type: SlotType, heard: str | None, target: str, s: Settings = default_settings) -> bool:
    """Does the heard value count as the target? Used by the Scorer (M4)."""
    if heard is None or not heard.strip():
        return False
    if slot_type == "person":
        return person_matches(heard, target, s)
    if slot_type == "time":
        return time_matches(heard, target)
    h, t = normalize_slot(slot_type, heard), normalize_slot(slot_type, target)
    if h is None or t is None:
        return False
    return h.lower() == t.lower()
