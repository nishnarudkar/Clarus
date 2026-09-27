"""M2: per-turn features on fixed word arrays (PROJECT.md §4.1, §7)."""

from __future__ import annotations

import pytest

from app.features import (
    clean_token,
    compute_turn_features,
    content_tokens,
    count_fillers,
    find_self_repair_markers,
    gaps_ms,
    jaccard,
    slot_span_conf,
)
from app.models import AaiWord


def W(text: str, start: int, end: int, conf: float = 0.9) -> AaiWord:
    return AaiWord(text=text, start=start, end=end, confidence=conf, word_is_final=True)


def seq(*items: str | tuple[str, float], gap: int = 100, dur: int = 200) -> list[AaiWord]:
    """Words laid out evenly: each `dur` ms long, separated by `gap` ms."""
    out, t = [], 0
    for item in items:
        text, conf = (item, 0.9) if isinstance(item, str) else item
        out.append(W(text, t, t + dur, conf))
        t += dur + gap
    return out


# Meet(0-300) Priya(400-700) [pause 600] at(1300-1500) gate(1550-1800) [long pause 1200] fifteen(3000-3500)
PRIYA = [
    W("Meet", 0, 300, 0.95),
    W("Priya", 400, 700, 0.80),
    W("at", 1300, 1500, 0.90),
    W("gate", 1550, 1800, 0.85),
    W("fifteen", 3000, 3500, 0.40),
]


def test_timing_features_on_fixed_array():
    f = compute_turn_features(PRIYA)
    assert f.word_count == 5
    assert f.duration_s == pytest.approx(3.5)
    assert f.speaking_rate_wpm == pytest.approx(5 / (3.5 / 60))  # ≈ 85.7
    assert gaps_ms(PRIYA) == [100, 600, 50, 1200]
    assert f.pause_count == 2  # 600, 1200 (>= 250)
    assert f.long_pause_count == 1  # 1200 (>= 1000)
    assert f.mean_pause_ms == pytest.approx(900)
    assert f.max_pause_ms == 1200


def test_confidence_features_on_fixed_array():
    f = compute_turn_features(PRIYA)
    assert f.mean_asr_conf == pytest.approx((0.95 + 0.80 + 0.90 + 0.85 + 0.40) / 5)
    assert f.min_asr_conf == pytest.approx(0.40)
    assert f.low_conf_frac == pytest.approx(1 / 5)  # only 0.40 < 0.6


def test_pause_threshold_boundaries():
    words = [W("a", 0, 100), W("b", 350, 400), W("c", 1400, 1500), W("d", 1749, 1800)]
    # gaps: 250 (pause), 1000 (long pause), 249 (not a pause)
    f = compute_turn_features(words)
    assert (f.pause_count, f.long_pause_count) == (2, 1)


def test_overlapping_words_do_not_make_negative_gaps():
    assert gaps_ms([W("a", 0, 300), W("b", 250, 400)]) == [0]


def test_empty_turn_is_well_defined():
    f = compute_turn_features([])
    assert (f.word_count, f.duration_s, f.speaking_rate_wpm) == (0, 0.0, None)
    assert (f.mean_asr_conf, f.min_asr_conf, f.low_conf_frac) == (None, None, None)
    assert (f.pause_count, f.mean_pause_ms, f.max_pause_ms) == (0, None, None)
    assert (f.filler_count, f.filler_rate) == (0, 0.0)


def test_single_word_has_no_pauses():
    f = compute_turn_features([W("yes", 0, 400)])
    assert f.speaking_rate_wpm == pytest.approx(150)
    assert f.pause_count == 0 and f.mean_pause_ms is None


def test_fillers_plain_tokens():
    words = seq("um,", "meet", "uh", "Priya", "Hmm.", "at", "gate", "erm")
    assert count_fillers(words) == 4
    f = compute_turn_features(words)
    assert f.filler_count == 4 and f.filler_rate == pytest.approx(4 / 8)


def test_discourse_fillers_need_commas():
    assert count_fillers(seq("So,", "like,", "gate", "15")) == 1
    assert count_fillers(seq("Like,", "meet", "Priya")) == 1  # turn-initial
    assert count_fillers(seq("You", "know,", "Thursday")) == 1
    assert count_fillers(seq("It's,", "you", "know,", "Thursday")) == 1
    # content uses: not counted
    assert count_fillers(seq("I", "like", "gate", "15")) == 0
    assert count_fillers(seq("do", "you", "know", "Priya")) == 0
    # unformatted turns have no commas, so discourse markers can't be detected
    assert count_fillers(seq("so", "like", "gate")) == 0


def test_self_repair_markers_mid_turn_only():
    words = seq("Gate", "fifty,", "sorry,", "I", "mean", "fifteen")
    assert find_self_repair_markers(words) == ["sorry", "i mean"]
    assert find_self_repair_markers(seq("Thursday,", "no", "wait,", "Tuesday")) == ["no wait"]
    assert find_self_repair_markers(seq("at", "four,", "actually", "four", "thirty")) == ["actually"]
    # turn-initial "Sorry" is not a self-repair (likely a repair request)
    assert find_self_repair_markers(seq("Sorry,", "what?")) == []
    assert compute_turn_features(words).self_repair_markers == ["sorry", "i mean"]


def test_repetition_overlap_against_previous_turn():
    prev = content_tokens(seq("meet", "Priya", "at", "gate", "fifteen"))
    same = seq("Meet", "Priya", "at", "gate", "fifteen.")
    f = compute_turn_features(same, previous_tokens=prev)
    assert f.repetition_overlap == pytest.approx(1.0) and f.is_repetition

    partial = seq("gate", "fifteen", "on", "Thursday")  # {gate, fifteen} / 6 tokens
    f = compute_turn_features(partial, previous_tokens=prev)
    assert f.repetition_overlap == pytest.approx(2 / 7)
    assert not f.is_repetition

    assert compute_turn_features(same).repetition_overlap is None  # no previous turn


def test_repetition_threshold_boundary():
    # 3 shared of 5 total = 0.6 -> repetition (>= threshold)
    prev = {"a", "b", "c", "d"}
    f = compute_turn_features(seq("a", "b", "c", "e"), previous_tokens=prev)
    assert f.repetition_overlap == pytest.approx(0.6) and f.is_repetition


def test_fillers_are_ignored_for_repetition():
    prev = content_tokens(seq("gate", "fifteen"))
    f = compute_turn_features(seq("um", "gate", "uh", "fifteen"), previous_tokens=prev)
    assert f.repetition_overlap == pytest.approx(1.0)


def test_repetition_ignores_number_formatting():
    prev = content_tokens(seq("Gate", "15."))  # formatted
    f = compute_turn_features(seq("gate", "fifteen"), previous_tokens=prev)  # unformatted
    assert f.repetition_overlap == pytest.approx(1.0)
    assert content_tokens(seq("gate", "one", "five")) == {"gate", "15"}


def test_jaccard_edge_cases():
    assert jaccard(set(), set()) is None
    assert jaccard({"a"}, set()) == 0.0


def test_slot_span_conf_uses_evidence_words():
    assert slot_span_conf(PRIYA, ["gate", "fifteen"]) == pytest.approx((0.85 + 0.40) / 2)
    assert slot_span_conf(PRIYA, ["Priya"]) == pytest.approx(0.80)
    assert slot_span_conf(PRIYA, []) is None
    assert slot_span_conf(PRIYA, ["tuesday"]) is None
    assert compute_turn_features(PRIYA, evidence_words=["fifteen"]).slot_span_conf == pytest.approx(0.40)
    assert compute_turn_features(PRIYA).slot_span_conf is None


def test_latency_to_respond():
    assert compute_turn_features(PRIYA, agent_speech_end_ms=-800).latency_to_respond_ms == 800
    assert compute_turn_features(PRIYA).latency_to_respond_ms is None


@pytest.mark.parametrize("raw,clean", [("Priya,", "priya"), ("15.", "15"), ("don't", "don't"), ("'bat'", "bat"), ("—", "")])
def test_clean_token(raw, clean):
    assert clean_token(raw) == clean
