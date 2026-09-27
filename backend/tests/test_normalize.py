"""M2: slot normalisers and matchers (PROJECT.md §3.1, §7)."""

from __future__ import annotations

import pytest

from app.normalize import (
    normalize_code_word,
    normalize_day,
    normalize_number,
    normalize_person,
    normalize_place,
    normalize_slot,
    normalize_time,
    numbers_to_digits,
    person_matches,
    slot_matches,
    time_matches,
    tokenize,
)

# -- number words ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("gate fifteen", ["gate", "15"]),
        ("gate fifty", ["gate", "50"]),
        ("gate one five", ["gate", "15"]),  # digit-by-digit clarification
        ("gate five zero", ["gate", "50"]),
        ("platform twenty one", ["platform", "21"]),
        ("room one hundred and five", ["room", "105"]),
        ("room three hundred", ["room", "300"]),
        ("four thirty", ["4", "30"]),  # unit then tens stays two numbers
        ("four oh five", ["405"]),
        ("gate 15", ["gate", "15"]),
        ("oh no", ["oh", "no"]),  # lone "oh" is not zero
    ],
)
def test_numbers_to_digits(text, expected):
    assert numbers_to_digits(tokenize(text)) == expected


def test_tokenize_handles_punctuation_and_glued_units():
    assert tokenize("Gate 15.") == ["gate", "15"]
    assert tokenize("4.30pm") == ["4:30", "pm"]
    assert tokenize("four o'clock") == ["four", "oclock"]
    assert tokenize("1,500") == ["1500"]


# -- person -----------------------------------------------------------------------


def test_normalize_person():
    assert normalize_person("  priya  ") == "Priya"
    assert normalize_person("mary-jane o'neil") == "Mary-jane O'neil"
    assert normalize_person("") is None


@pytest.mark.parametrize(
    "heard,target,ok",
    [
        ("priya", "Priya", True),  # case-insensitive
        ("Priyah", "Priya", True),  # fuzzy >= 0.85 (0.91)
        ("Rabi", "Ravi", False),  # confusable pair stays distinct (0.75)
        ("Anna", "Hannah", False),  # (0.80)
        ("Hannah", "Hannah", True),
        ("", "Priya", False),
    ],
)
def test_person_matches(heard, target, ok):
    assert person_matches(heard, target) is ok


# -- place ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Gate 15", "Gate 15"),
        ("gate fifteen", "Gate 15"),
        ("at gate one five", "Gate 15"),
        ("the gate fifty", "Gate 50"),
        ("platform thirteen", "Platform 13"),
        ("gate", "Gate"),
        ("at the", None),
    ],
)
def test_normalize_place(text, expected):
    assert normalize_place(text) == expected


def test_place_teen_ty_confusables_do_not_match():
    assert slot_matches("place", "gate fifteen", "Gate 15")
    assert not slot_matches("place", "gate fifty", "Gate 15")
    assert not slot_matches("place", "gate thirty", "Gate 13")
    assert not slot_matches("place", "gate forty", "Gate 14")


# -- day --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Thursday", "thursday"),
        ("on thursday.", "thursday"),
        ("thurs", "thursday"),
        ("Tue", "tuesday"),
        ("next Tuesday's meeting", "tuesday"),
        ("sundays", "sunday"),
        ("tomorrow", None),
        ("tuesday or thursday", None),  # ambiguous
    ],
)
def test_normalize_day(text, expected):
    assert normalize_day(text) == expected


def test_day_confusables_do_not_match():
    assert slot_matches("day", "on Thursday", "Thursday")
    assert not slot_matches("day", "Tuesday", "Thursday")


# -- time -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,hhmm,explicit",
    [
        ("4:30", "04:30", False),
        ("4.30", "04:30", False),
        ("16:30", "16:30", True),
        ("09:15", "09:15", True),  # zero-padded = 24-hour
        ("half past four", "04:30", False),
        ("four thirty pm", "16:30", True),
        ("4:30 p.m.", "16:30", True),
        ("4:30pm", "16:30", True),
        ("four thirty", "04:30", False),
        ("four fifteen", "04:15", False),
        ("four forty five", "04:45", False),
        ("four oh five", "04:05", False),
        ("quarter past four", "04:15", False),
        ("quarter to five", "04:45", False),
        ("quarter to one", "12:45", False),
        ("twenty past four", "04:20", False),
        ("ten to five in the afternoon", "16:50", True),
        ("four o'clock", "04:00", False),
        ("4 pm", "16:00", True),
        ("at four in the afternoon", "16:00", True),
        ("12:30 am", "00:30", True),
        ("twelve pm", "12:00", True),
        ("noon", "12:00", True),
        ("midnight", "00:00", True),
        ("1630", "16:30", True),
        ("four", "04:00", False),
    ],
)
def test_normalize_time(text, hhmm, explicit):
    t = normalize_time(text)
    assert t is not None, text
    assert (t.hhmm, t.explicit) == (hhmm, explicit)


@pytest.mark.parametrize("text", ["", "thursday", "25:00", "4:75", "gate"])
def test_normalize_time_rejects(text):
    assert normalize_time(text) is None


@pytest.mark.parametrize(
    "heard,target,ok",
    [
        ("4:30", "16:30", True),  # §3.1: accept "4:30" for 16:30
        ("half past four", "16:30", True),
        ("four thirty pm", "16:30", True),
        ("4:30 am", "16:30", False),  # explicit and wrong
        ("four fifteen", "16:30", False),
        ("9:15 pm", "09:15", False),
        ("9:15", "09:15", True),
        ("quarter past nine in the morning", "09:15", True),
        ("thursday", "16:30", False),
    ],
)
def test_time_matches(heard, target, ok):
    assert time_matches(heard, target) is ok


# -- number / code word -----------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [("fifteen", 15), ("one five", 15), ("15", 15), ("forty two", 42), ("1,500", 1500), ("two and three", None), ("none", None)],
)
def test_normalize_number(text, expected):
    assert normalize_number(text) == expected


@pytest.mark.parametrize("text,expected", [("BAT", "bat"), ("bat.", "bat"), (" 'Bat' ", "bat"), ("", None)])
def test_normalize_code_word(text, expected):
    assert normalize_code_word(text) == expected


def test_code_word_is_exact_after_lowercasing():
    assert slot_matches("code_word", "Bat", "bat")
    for rhyme in ["pat", "cat", "mat", "that", "sat"]:
        assert not slot_matches("code_word", rhyme, "bat")


# -- dispatch ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "slot_type,value,expected",
    [
        ("person", "priya", "Priya"),
        ("place", "gate fifteen", "Gate 15"),
        ("day", "thurs", "thursday"),
        ("time", "half past four", "04:30"),
        ("number", "fifteen", "15"),
        ("code_word", "BAT", "bat"),
        ("place", None, None),
        ("time", "   ", None),
    ],
)
def test_normalize_slot_dispatch(slot_type, value, expected):
    assert normalize_slot(slot_type, value) == expected


def test_normalize_slot_rejects_unknown_type():
    with pytest.raises(ValueError):
        normalize_slot("colour", "red")  # type: ignore[arg-type]


def test_slot_matches_card_007():
    """The example card from PROJECT.md §3.1, heard correctly and via confusables."""
    target = {"person": "Priya", "place": "Gate 15", "day": "Thursday", "time": "16:30", "code_word": "bat"}
    heard_ok = {"person": "priya", "place": "gate one five", "day": "thursday", "time": "half past four", "code_word": "BAT"}
    heard_bad = {"person": "Priya", "place": "Gate 50", "day": "Tuesday", "time": "4:30", "code_word": "pat"}
    assert all(slot_matches(k, heard_ok[k], v) for k, v in target.items())  # type: ignore[arg-type]
    assert [k for k, v in target.items() if not slot_matches(k, heard_bad[k], v)] == ["place", "day", "code_word"]  # type: ignore[arg-type]
    assert not slot_matches("person", None, "Priya")
