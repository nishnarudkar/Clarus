"""Client for AssemblyAI Universal-Streaming v3 over WebSocket.

Wire protocol (checked against the official SDKs, see docs/DECISIONS.md):
- URL: wss://streaming.assemblyai.com/v3/ws?<params>
- Auth: `Authorization: <API_KEY>` header (server side only).
- Audio: binary PCM16 mono frames, 50–1000 ms each.
- Control: {"type": "Terminate"} for a clean shutdown; server replies with
  any final Turn and then {"type": "Termination", ...}.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlencode

from .config import Settings
from .models import AaiMessage, AaiTermination, parse_aai_message

logger = logging.getLogger(__name__)

# WebSocket close codes / HTTP statuses that retrying cannot fix
# (not authorised, insufficient funds, paid-only feature, too many streams).
FATAL_CODES = {401, 402, 403, 4001, 4002, 4003, 4102}


class UpstreamSocket(Protocol):
    async def send(self, message: str | bytes) -> None: ...
    async def recv(self) -> str | bytes: ...
    async def close(self, code: int = 1000, reason: str = "") -> None: ...


Connector = Callable[[str, dict[str, str], float], Awaitable[UpstreamSocket]]


async def default_connector(url: str, headers: dict[str, str], timeout: float) -> UpstreamSocket:
    from websockets.asyncio.client import connect

    return await connect(url, additional_headers=headers, open_timeout=timeout, max_size=None)


class UpstreamConnectError(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code

    @property
    def fatal(self) -> bool:
        return self.code in FATAL_CODES


@dataclass
class CloseInfo:
    clean: bool  # True if we asked for it (Terminate) or the server said Termination
    code: int | None = None
    reason: str = ""

    @property
    def fatal(self) -> bool:
        return self.code in FATAL_CODES


def build_stream_url(settings: Settings) -> str:
    params: dict[str, Any] = {
        "sample_rate": settings.streaming_sample_rate,
        "encoding": "pcm_s16le",
        "speech_model": settings.streaming_speech_model,
        "format_turns": str(settings.streaming_format_turns).lower(),
    }
    if settings.end_of_turn_confidence_threshold is not None:
        params["end_of_turn_confidence_threshold"] = settings.end_of_turn_confidence_threshold
    if settings.min_turn_silence_ms is not None:
        params["min_turn_silence"] = settings.min_turn_silence_ms
    if settings.max_turn_silence_ms is not None:
        params["max_turn_silence"] = settings.max_turn_silence_ms
    host = settings.streaming_host
    base = host if host.startswith(("ws://", "wss://")) else f"wss://{host}"
    return f"{base}/v3/ws?{urlencode(params)}"


def build_headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": settings.assemblyai_api_key,
        "AssemblyAI-Version": settings.assemblyai_version_header,
    }


def _close_details(exc: BaseException) -> tuple[int | None, str]:
    """Pull a close code/reason out of a websockets ConnectionClosed (or anything alike)."""
    rcvd = getattr(exc, "rcvd", None)
    if rcvd is not None:
        return getattr(rcvd, "code", None), getattr(rcvd, "reason", "") or ""
    return getattr(exc, "code", None), getattr(exc, "reason", "") or str(exc)


class AssemblyAIStreamClient:
    """One upstream streaming session. Create a new instance to reconnect."""

    def __init__(
        self,
        settings: Settings,
        on_message: Callable[[AaiMessage], Awaitable[None]],
        connector: Connector = default_connector,
    ):
        self._settings = settings
        self._on_message = on_message
        self._connector = connector
        self._ws: UpstreamSocket | None = None
        self._reader: asyncio.Task[CloseInfo] | None = None
        self._terminating = False
        self._terminated = asyncio.Event()

    async def open(self) -> None:
        if not self._settings.assemblyai_api_key:
            raise UpstreamConnectError("ASSEMBLYAI_API_KEY is not set on the server", code=401)
        try:
            self._ws = await self._connector(
                build_stream_url(self._settings),
                build_headers(self._settings),
                self._settings.upstream_connect_timeout_s,
            )
        except UpstreamConnectError:
            raise
        except Exception as exc:  # handshake rejected, DNS, timeout, …
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            raise UpstreamConnectError(f"Could not connect to AssemblyAI: {exc}", code=status) from exc
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> CloseInfo:
        assert self._ws is not None
        try:
            while True:
                raw = await self._ws.recv()
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = parse_aai_message(json.loads(raw))
                except Exception:
                    logger.warning("Unparseable AssemblyAI message: %.200s", raw)
                    continue
                await self._on_message(msg)
                if isinstance(msg, AaiTermination):
                    self._terminated.set()
                    await self._ws.close()
                    return CloseInfo(clean=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code, reason = _close_details(exc)
            clean = self._terminating or code == 1000
            if not clean:
                logger.warning("AssemblyAI stream closed unexpectedly: code=%s reason=%s", code, reason)
            return CloseInfo(clean=clean, code=code, reason=reason)
        finally:
            self._terminated.set()

    async def send_audio(self, chunk: bytes) -> bool:
        """Forward one PCM16 frame. Returns False if the stream isn't writable."""
        if self._ws is None or self._terminating or self._terminated.is_set():
            return False
        try:
            await self._ws.send(chunk)
            return True
        except Exception:
            return False  # the read loop reports the close

    async def wait_closed(self) -> CloseInfo:
        assert self._reader is not None
        try:
            return await asyncio.shield(self._reader)
        except asyncio.CancelledError:
            if self._reader.cancelled():  # reader stopped by terminate(), not us
                return CloseInfo(clean=True)
            raise

    async def terminate(self) -> None:
        """Clean shutdown: send Terminate, wait for Termination (bounded), close."""
        if self._ws is None or self._terminating:
            return
        self._terminating = True
        if not self._terminated.is_set():
            try:
                await self._ws.send(json.dumps({"type": "Terminate"}))
                await asyncio.wait_for(self._terminated.wait(), self._settings.upstream_terminate_timeout_s)
            except Exception:
                logger.info("No Termination from AssemblyAI before timeout; closing")
        try:
            await self._ws.close()
        except Exception:
            pass
        if self._reader is not None and not self._reader.done():
            # Closing the socket ends recv(); give the reader a moment, then force it.
            done, _ = await asyncio.wait({self._reader}, timeout=1.0)
            if not done:
                self._reader.cancel()
