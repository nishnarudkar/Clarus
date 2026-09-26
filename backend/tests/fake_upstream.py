"""In-memory stand-in for the AssemblyAI streaming WebSocket (no network)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field


class FakeClosed(Exception):
    def __init__(self, code: int, reason: str = ""):
        super().__init__(f"closed {code} {reason}")
        self.code = code
        self.reason = reason


def turn(order: int, words: list[tuple[str, float]], end: bool, formatted: bool = False) -> dict:
    return {
        "type": "Turn",
        "turn_order": order,
        "turn_is_formatted": formatted,
        "end_of_turn": end,
        "transcript": " ".join(w for w, _ in words),
        "end_of_turn_confidence": 0.9 if end else 0.1,
        "words": [
            {"text": w, "start": i * 300, "end": i * 300 + 250, "confidence": c, "word_is_final": end}
            for i, (w, c) in enumerate(words)
        ],
    }


@dataclass
class FakeUpstream:
    """Replies to the Nth audio frame with `script[N]` (a list of messages or a FakeClosed)."""

    script: list = field(default_factory=list)
    url: str = ""
    headers: dict = field(default_factory=dict)
    sent_audio: list[bytes] = field(default_factory=list)
    sent_control: list[dict] = field(default_factory=list)
    closed: bool = False

    def __post_init__(self) -> None:
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.inbox.put_nowait(json.dumps({"type": "Begin", "id": "sess-fake", "expires_at": 1_900_000_000}))

    async def send(self, message: str | bytes) -> None:
        if isinstance(message, bytes):
            idx = len(self.sent_audio)
            self.sent_audio.append(message)
            if idx < len(self.script):
                step = self.script[idx]
                if isinstance(step, FakeClosed):
                    self.inbox.put_nowait(step)
                else:
                    for m in step:
                        self.inbox.put_nowait(json.dumps(m))
            return
        data = json.loads(message)
        self.sent_control.append(data)
        if data.get("type") == "Terminate":
            self.inbox.put_nowait(json.dumps({"type": "Termination", "audio_duration_seconds": 1}))

    async def recv(self) -> str:
        item = await self.inbox.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self, code: int = 1000, reason: str = "") -> None:
        if not self.closed:
            self.closed = True
            self.inbox.put_nowait(FakeClosed(1000))


class FakeConnector:
    """Hands out prepared FakeUpstreams (or raises prepared exceptions) in order."""

    def __init__(self, *items):
        self.items = list(items)
        self.connections: list[FakeUpstream] = []

    async def __call__(self, url: str, headers: dict, timeout: float):
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        item.url, item.headers = url, headers
        self.connections.append(item)
        return item
