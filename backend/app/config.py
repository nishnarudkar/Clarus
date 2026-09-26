"""Central configuration: every threshold, weight and model name lives here.

Values can be overridden with environment variables (loaded from the repo-root
`.env` if present). See PROJECT.md §11: no hidden magic numbers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value and value.strip() else default


def _env_opt_int(name: str) -> int | None:
    value = os.getenv(name)
    return int(value) if value and value.strip() else None


def _env_opt_float(name: str) -> float | None:
    value = os.getenv(name)
    return float(value) if value and value.strip() else None


@dataclass(frozen=True)
class Settings:
    # --- AssemblyAI Universal-Streaming (v3) --------------------------------
    # Secret; never sent to the browser.
    assemblyai_api_key: str = field(default_factory=lambda: os.getenv("ASSEMBLYAI_API_KEY", "").strip())
    # Host of the v3 streaming endpoint; the client connects to wss://<host>/v3/ws
    # (a ws:// or wss:// prefix is used as given, e.g. for a local test server).
    streaming_host: str = field(default_factory=lambda: _env_str("STREAMING_HOST", "streaming.assemblyai.com"))
    # Streaming model. universal-3-5-pro is what the official SDK examples use (see docs/DECISIONS.md).
    streaming_speech_model: str = field(default_factory=lambda: _env_str("STREAMING_SPEECH_MODEL", "universal-3-5-pro"))
    # PCM16 mono sample rate the browser sends and AssemblyAI expects.
    streaming_sample_rate: int = field(default_factory=lambda: _env_int("STREAMING_SAMPLE_RATE", 16000))
    # Ask for punctuated/cased final turns (a second end_of_turn message with turn_is_formatted=true).
    streaming_format_turns: bool = True
    # Turn-detection tuning. None = don't send the parameter, so the model's own default applies
    # (defaults differ between streaming models and could not be verified; see docs/DECISIONS.md).
    # Confidence needed to end a turn (0-1).
    end_of_turn_confidence_threshold: float | None = field(default_factory=lambda: _env_opt_float("END_OF_TURN_CONFIDENCE_THRESHOLD"))
    # Silence (ms) before ending a turn when the model is confident the turn is over.
    min_turn_silence_ms: int | None = field(default_factory=lambda: _env_opt_int("MIN_TURN_SILENCE_MS"))
    # Maximum silence (ms) before a turn is forced to end.
    max_turn_silence_ms: int | None = field(default_factory=lambda: _env_opt_int("MAX_TURN_SILENCE_MS"))
    # AssemblyAI API version header sent by the official SDKs.
    assemblyai_version_header: str = "2025-05-12"
    # Seconds to wait for the WebSocket handshake with AssemblyAI.
    upstream_connect_timeout_s: float = 10.0
    # Seconds to wait for Termination after sending Terminate on clean shutdown.
    upstream_terminate_timeout_s: float = 5.0
    # Reconnect policy after an unexpected upstream drop: attempts and base backoff (doubles each time).
    upstream_max_reconnect_attempts: int = 4
    upstream_reconnect_backoff_s: float = 0.5

    # --- Word-confidence bands for the live transcript (PROJECT.md §6) -----
    # green >= high, amber in [low, high), red < low.
    conf_band_high: float = 0.85
    conf_band_low: float = 0.6

    # --- Per-turn features (PROJECT.md §4.1) --------------------------------
    # Inter-word gap (ms) that counts as a pause.
    pause_min_ms: int = 250
    # Inter-word gap (ms) that counts as a long pause.
    long_pause_min_ms: int = 1000
    # A word below this ASR confidence counts toward low_conf_frac.
    low_conf_threshold: float = 0.6
    # Token Jaccard with the previous user turn at or above this => repetition.
    repetition_jaccard_threshold: float = 0.6
    # Filler tokens, always counted.
    fillers: tuple[str, ...] = ("um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm", "mm")
    # Discourse-marker fillers, counted only when set off by a comma in formatted text
    # ("so, like, gate 15" / "you know, thursday"); a simple heuristic, see docs/DECISIONS.md.
    discourse_fillers: tuple[str, ...] = ("like", "you know")
    # Self-repair markers; counted only mid-turn (at least one word before them).
    self_repair_markers: tuple[str, ...] = ("sorry", "i mean", "no wait", "actually", "rather", "correction")

    # --- Slot normalisers (PROJECT.md §3.1) ---------------------------------
    # Person names match if difflib similarity (case-insensitive) is at least this.
    # 0.85 keeps confusable pairs apart: Ravi/Rabi = 0.75, Anna/Hannah = 0.80.
    person_fuzzy_threshold: float = 0.85


settings = Settings()
