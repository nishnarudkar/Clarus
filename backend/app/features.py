"""Per-turn features from a final Turn's words (PROJECT.md §4.1). Pure functions.

Word timestamps are ms on the AssemblyAI stream clock. Thresholds and word
lists live in config.py.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Protocol

from .config import Settings, settings as default_settings
from .models import TurnFeatures
from .normalize import numbers_to_digits


class TimedWord(Protocol):
    text: str
    start: int
    end: int
    confidence: float


def clean_token(text: str) -> str:
    """'Priya,' -> 'priya'; "don't" stays "don't"."""
    return re.sub(r"[^\w']+", "", text.lower()).strip("'")


def gaps_ms(words: Sequence[TimedWord]) -> list[int]:
    """Silence between consecutive words (overlaps count as 0)."""
    return [max(0, b.start - a.end) for a, b in zip(words, words[1:])]


def count_fillers(words: Sequence[TimedWord], s: Settings = default_settings) -> int:
    tokens = [clean_token(w.text) for w in words]
    raw = [w.text.lower() for w in words]
    count = sum(1 for t in tokens if t in s.fillers)
    # Discourse markers ("like", "you know") only when set off by commas, which
    # needs punctuation, i.e. formatted turns. Otherwise "I like it" would count.
    for marker in s.discourse_fillers:
        parts = marker.split()
        n = len(parts)
        for i in range(len(tokens) - n + 1):
            if tokens[i : i + n] != parts:
                continue
            set_off_before = i == 0 or raw[i - 1].endswith(",")
            if set_off_before and raw[i + n - 1].endswith(","):
                count += 1
    return count


def find_self_repair_markers(words: Sequence[TimedWord], s: Settings = default_settings) -> list[str]:
    """Markers found mid-turn (not as the first word), in order of appearance."""
    tokens = [clean_token(w.text) for w in words]
    found: list[tuple[int, str]] = []
    for marker in s.self_repair_markers:
        parts = marker.split()
        n = len(parts)
        for i in range(1, len(tokens) - n + 1):
            if tokens[i : i + n] == parts:
                found.append((i, marker))
    return [m for _, m in sorted(found)]


def content_tokens(words: Iterable[TimedWord], s: Settings = default_settings) -> set[str]:
    """Tokens compared for repetition: fillers dropped, number words as digits
    (formatted turns write "15" where unformatted ones say "fifteen")."""
    tokens = [t for w in words if (t := clean_token(w.text)) and t not in s.fillers]
    return set(numbers_to_digits(tokens))


def jaccard(a: set[str], b: set[str]) -> float | None:
    if not a and not b:
        return None
    return len(a & b) / len(a | b)


def slot_span_conf(words: Sequence[TimedWord], evidence_words: Iterable[str] | None) -> float | None:
    """Mean confidence of the words the interpreter cites as evidence for slot values."""
    if not evidence_words:
        return None
    evidence = {clean_token(e) for e in evidence_words}
    confs = [w.confidence for w in words if clean_token(w.text) in evidence]
    return sum(confs) / len(confs) if confs else None


def compute_turn_features(
    words: Sequence[TimedWord],
    *,
    previous_tokens: set[str] | None = None,
    agent_speech_end_ms: int | None = None,
    evidence_words: Iterable[str] | None = None,
    s: Settings = default_settings,
) -> TurnFeatures:
    n = len(words)
    duration_s = max(0, words[-1].end - words[0].start) / 1000 if n else 0.0
    pauses = [g for g in gaps_ms(words) if g >= s.pause_min_ms]
    confs = [w.confidence for w in words]
    fillers = count_fillers(words, s)
    overlap = jaccard(content_tokens(words, s), previous_tokens) if previous_tokens is not None else None

    return TurnFeatures(
        word_count=n,
        duration_s=duration_s,
        speaking_rate_wpm=n / (duration_s / 60) if duration_s > 0 else None,
        pause_count=len(pauses),
        long_pause_count=sum(1 for g in pauses if g >= s.long_pause_min_ms),
        mean_pause_ms=sum(pauses) / len(pauses) if pauses else None,
        max_pause_ms=max(pauses) if pauses else None,
        filler_count=fillers,
        filler_rate=fillers / n if n else 0.0,
        mean_asr_conf=sum(confs) / n if n else None,
        min_asr_conf=min(confs) if n else None,
        low_conf_frac=sum(1 for c in confs if c < s.low_conf_threshold) / n if n else None,
        slot_span_conf=slot_span_conf(words, evidence_words),
        self_repair_markers=find_self_repair_markers(words, s),
        repetition_overlap=overlap,
        is_repetition=overlap is not None and overlap >= s.repetition_jaccard_threshold,
        latency_to_respond_ms=(words[0].start - agent_speech_end_ms) if (n and agent_speech_end_ms is not None) else None,
    )
