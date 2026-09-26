"""Browser WebSocket endpoint `/ws/session/{id}`: relays mic audio to AssemblyAI
and streams transcript events back (PROJECT.md §8 "Browser WS protocol").

Client → server: binary PCM16 frames (16 kHz mono, 50–1000 ms each) and JSON
control messages (`start_stream`, `stop_stream`, `end_session`).
Server → client: `state`, `partial_transcript`, `final_turn`, `error`.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from .assemblyai_stream import AssemblyAIStreamClient, Connector, UpstreamConnectError, default_connector
from .config import Settings, settings as default_settings
from .features import compute_turn_features, content_tokens
from .models import (
    AaiBegin,
    AaiError,
    AaiMessage,
    AaiTurn,
    AaiWord,
    ClientEndSession,
    ClientStartStream,
    ClientStopStream,
    ConfBand,
    ServerError,
    ServerEvent,
    ServerFinalTurn,
    ServerPartialTranscript,
    ServerState,
    WordOut,
    client_message_adapter,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Overridable in tests so no network is touched.
connector_override: Connector | None = None
settings_override: Settings | None = None


def confidence_band(confidence: float, s: Settings) -> ConfBand:
    if confidence >= s.conf_band_high:
        return "high"
    if confidence >= s.conf_band_low:
        return "mid"
    return "low"


def _words_out(words: list[AaiWord], s: Settings) -> list[WordOut]:
    return [
        WordOut(
            text=w.text,
            start=w.start,
            end=w.end,
            confidence=w.confidence,
            band=confidence_band(w.confidence, s),
            final=w.word_is_final,
        )
        for w in words
    ]


class StreamSession:
    def __init__(self, websocket: WebSocket, session_id: str, s: Settings, connector: Connector):
        self.ws = websocket
        self.session_id = session_id
        self.settings = s
        self.connector = connector
        self.upstream: AssemblyAIStreamClient | None = None
        self.want_stream = False
        self._supervisor: asyncio.Task[None] | None = None
        self._attempts = 0
        self._stream_id = ""
        # Repetition is measured against the previous *distinct* user turn; the
        # formatted re-send of a turn must not count as a repeat of itself.
        self._last_turn_key: tuple[str, int] | None = None
        self._last_turn_tokens: set[str] | None = None
        self._prev_turn_tokens: set[str] | None = None
        self._send_lock = asyncio.Lock()
        self._browser_open = True

    # -- browser side -------------------------------------------------------

    async def send(self, event: ServerEvent) -> None:
        if not self._browser_open:
            return
        async with self._send_lock:
            try:
                await self.ws.send_text(event.model_dump_json())
            except Exception:
                self._browser_open = False

    async def run(self) -> None:
        await self.send(ServerState(state="idle"))
        try:
            while True:
                msg = await self.ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    if self.upstream is not None:
                        await self.upstream.send_audio(msg["bytes"])
                    continue
                text = msg.get("text")
                if text is None:
                    continue
                try:
                    control = client_message_adapter.validate_json(text)
                except ValidationError as exc:
                    await self.send(ServerError(message=f"Invalid control message: {exc.errors()[0]['msg']}", recoverable=True))
                    continue
                if isinstance(control, ClientStartStream):
                    await self.start_stream()
                elif isinstance(control, ClientStopStream):
                    await self.stop_stream()
                elif isinstance(control, ClientEndSession):
                    break
        except WebSocketDisconnect:
            pass
        finally:
            self._browser_open = self._browser_open and self.ws.client_state.name == "CONNECTED"
            await self.stop_stream()
            if self._browser_open:
                await self.ws.close()

    # -- upstream side ------------------------------------------------------

    async def start_stream(self) -> None:
        if self._supervisor is not None and not self._supervisor.done():
            return
        self.want_stream = True
        self._attempts = 0
        self._supervisor = asyncio.create_task(self._supervise())

    async def stop_stream(self) -> None:
        if self._supervisor is None:
            return
        self.want_stream = False
        await self.send(ServerState(state="stopping"))
        if self.upstream is not None:
            await self.upstream.terminate()
        done, _ = await asyncio.wait({self._supervisor}, timeout=self.settings.upstream_terminate_timeout_s + 2)
        if not done:
            self._supervisor.cancel()
        self._supervisor = None
        await self.send(ServerState(state="stopped"))

    async def _supervise(self) -> None:
        """Open the upstream stream and reconnect after unexpected drops."""
        s = self.settings
        await self.send(ServerState(state="connecting"))
        while self.want_stream:
            client = AssemblyAIStreamClient(s, self._on_upstream_message, self.connector)
            try:
                await client.open()
            except UpstreamConnectError as exc:
                logger.warning("Upstream connect failed: %s", exc)
                if not await self._retry_or_give_up(str(exc), exc.code, exc.fatal):
                    return
                continue
            if not self.want_stream:  # stop requested while connecting
                await client.terminate()
                return
            self.upstream = client
            info = await client.wait_closed()
            self.upstream = None
            if not self.want_stream:
                return
            # The stream ended without us asking (network drop, session expiry, server error).
            reason = info.reason or "AssemblyAI stream closed unexpectedly"
            if not await self._retry_or_give_up(reason, info.code, info.fatal):
                return

    async def _retry_or_give_up(self, message: str, code: int | None, fatal: bool) -> bool:
        s = self.settings
        if fatal or self._attempts >= s.upstream_max_reconnect_attempts:
            self.want_stream = False
            await self.send(ServerError(message=message, code=code, recoverable=False))
            await self.send(ServerState(state="stopped", detail=message))
            self._supervisor = None
            return False
        delay = s.upstream_reconnect_backoff_s * (2**self._attempts)
        self._attempts += 1
        await self.send(ServerError(message=message, code=code, recoverable=True))
        await self.send(ServerState(state="reconnecting", detail=f"attempt {self._attempts}"))
        await asyncio.sleep(delay)
        return self.want_stream

    async def _on_upstream_message(self, msg: AaiMessage) -> None:
        s = self.settings
        if isinstance(msg, AaiBegin):
            self._attempts = 0
            self._stream_id = msg.id
            await self.send(ServerState(state="listening"))
        elif isinstance(msg, AaiTurn):
            words = _words_out(msg.words, s)
            if msg.end_of_turn:
                key = (self._stream_id, msg.turn_order)
                if key != self._last_turn_key:
                    self._prev_turn_tokens = self._last_turn_tokens
                    self._last_turn_key = key
                features = compute_turn_features(msg.words, previous_tokens=self._prev_turn_tokens, s=s)
                self._last_turn_tokens = content_tokens(msg.words, s)
                await self.send(
                    ServerFinalTurn(
                        stream_id=self._stream_id,
                        turn_order=msg.turn_order,
                        text=msg.transcript,
                        formatted=msg.turn_is_formatted,
                        end_of_turn_confidence=msg.end_of_turn_confidence,
                        words=words,
                        features=features,
                    )
                )
            else:
                await self.send(ServerPartialTranscript(stream_id=self._stream_id, turn_order=msg.turn_order, text=msg.transcript, words=words))
        elif isinstance(msg, AaiError):
            logger.warning("AssemblyAI error %s: %s", msg.error_code, msg.error)
            await self.send(ServerError(message=f"AssemblyAI: {msg.error}", code=msg.error_code, recoverable=True))


@router.websocket("/ws/session/{session_id}")
async def session_socket(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    session = StreamSession(
        websocket,
        session_id,
        settings_override or default_settings,
        connector_override or default_connector,
    )
    await session.run()
