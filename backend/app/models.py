"""Pydantic models for every message crossing a boundary (PROJECT.md §11).

Two boundaries so far:
- AssemblyAI Universal-Streaming v3 → backend (`Aai*` models).
- Backend ↔ browser over `/ws/session/{id}` (`Client*` in, `Server*` out).
"""

from __future__ import annotations

import time
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


def now_ms() -> int:
    return int(time.time() * 1000)


# --------------------------------------------------------------------------
# AssemblyAI Universal-Streaming v3 (server → us). Unknown fields are ignored
# so additive API changes don't break parsing.
# --------------------------------------------------------------------------


class _AaiModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AaiWord(_AaiModel):
    text: str
    start: int  # ms from stream start
    end: int  # ms from stream start
    confidence: float
    word_is_final: bool


class AaiBegin(_AaiModel):
    type: Literal["Begin"]
    id: str
    expires_at: int | str | None = None


class AaiTurn(_AaiModel):
    type: Literal["Turn"]
    turn_order: int
    turn_is_formatted: bool = False
    end_of_turn: bool
    transcript: str
    end_of_turn_confidence: float = 0.0
    words: list[AaiWord] = Field(default_factory=list)


class AaiTermination(_AaiModel):
    type: Literal["Termination"]
    audio_duration_seconds: float | None = None
    session_duration_seconds: float | None = None


class AaiError(_AaiModel):
    type: Literal["Error"] = "Error"
    error_code: int | None = None
    error: str


class AaiOther(_AaiModel):
    """SpeechStarted, Warning, Heartbeat, Silence, … — not used yet."""

    model_config = ConfigDict(extra="allow")
    type: str


AaiMessage = Union[AaiBegin, AaiTurn, AaiTermination, AaiError, AaiOther]


def parse_aai_message(data: dict) -> AaiMessage:
    kind = data.get("type")
    if kind == "Begin":
        return AaiBegin.model_validate(data)
    if kind == "Turn":
        return AaiTurn.model_validate(data)
    if kind == "Termination":
        return AaiTermination.model_validate(data)
    if kind == "Error" or (kind is None and "error" in data):
        return AaiError.model_validate(data)
    return AaiOther.model_validate(data)


# --------------------------------------------------------------------------
# Browser → backend control messages (JSON text frames; audio is binary).
# --------------------------------------------------------------------------


class ClientStartStream(BaseModel):
    type: Literal["start_stream"]


class ClientStopStream(BaseModel):
    type: Literal["stop_stream"]


class ClientEndSession(BaseModel):
    type: Literal["end_session"]


ClientMessage = Annotated[
    Union[ClientStartStream, ClientStopStream, ClientEndSession],
    Field(discriminator="type"),
]
client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


# --------------------------------------------------------------------------
# Backend → browser events. All carry `ts` (ms since epoch).
# --------------------------------------------------------------------------

ConfBand = Literal["high", "mid", "low"]
StreamState = Literal["idle", "connecting", "listening", "reconnecting", "stopping", "stopped"]


class _ServerEvent(BaseModel):
    ts: int = Field(default_factory=now_ms)


class WordOut(BaseModel):
    text: str
    start: int
    end: int
    confidence: float
    band: ConfBand
    final: bool


class ServerState(_ServerEvent):
    type: Literal["state"] = "state"
    state: StreamState
    detail: str | None = None


class ServerPartialTranscript(_ServerEvent):
    type: Literal["partial_transcript"] = "partial_transcript"
    stream_id: str  # AssemblyAI session id; turn_order restarts at 0 after a reconnect
    turn_order: int
    text: str
    words: list[WordOut]


class TurnFeatures(BaseModel):
    """Per-turn acoustic/prosodic/lexical features (PROJECT.md §4.1).
    None means "not defined for this turn" (e.g. no pauses, no previous turn)."""

    word_count: int
    duration_s: float
    speaking_rate_wpm: float | None
    pause_count: int
    long_pause_count: int
    mean_pause_ms: float | None
    max_pause_ms: int | None
    filler_count: int
    filler_rate: float  # fillers / words
    mean_asr_conf: float | None
    min_asr_conf: float | None
    low_conf_frac: float | None
    slot_span_conf: float | None  # needs interpreter evidence_words (M3)
    self_repair_markers: list[str]
    repetition_overlap: float | None  # token Jaccard with the previous user turn
    is_repetition: bool
    latency_to_respond_ms: int | None  # needs agent speech end (M3)


class ServerFinalTurn(_ServerEvent):
    """A finished user turn. With format_turns, the same `turn_order` may arrive
    twice: first unformatted, then formatted — clients upsert by (stream_id, turn_order)."""

    type: Literal["final_turn"] = "final_turn"
    stream_id: str
    turn_order: int
    text: str
    formatted: bool
    end_of_turn_confidence: float
    words: list[WordOut]
    features: TurnFeatures


class ServerError(_ServerEvent):
    type: Literal["error"] = "error"
    message: str
    code: int | None = None
    # True if the backend will retry on its own; False needs user action.
    recoverable: bool


ServerEvent = Union[ServerState, ServerPartialTranscript, ServerFinalTurn, ServerError]
