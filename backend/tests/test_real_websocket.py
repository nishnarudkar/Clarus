"""The real `websockets` connector against a local fake AssemblyAI server (localhost only)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest
from websockets.asyncio.server import serve

from app.assemblyai_stream import AssemblyAIStreamClient
from app.models import AaiBegin, AaiTermination, AaiTurn

from .fake_upstream import turn
from .test_stream import TEST_SETTINGS


async def _run(handler, messages: list):
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        settings = replace(TEST_SETTINGS, streaming_host=f"ws://127.0.0.1:{port}")

        async def on_message(m):
            messages.append(m)

        client = AssemblyAIStreamClient(settings, on_message)
        await client.open()
        return client, await _drive(client)


async def _drive(client):
    await client.send_audio(b"\x00\x00" * 1600)
    await asyncio.sleep(0.05)
    await client.terminate()
    return await client.wait_closed()


def test_real_connector_handshake_turns_and_terminate():
    seen = {}

    async def handler(ws):
        seen["path"] = ws.request.path
        seen["auth"] = ws.request.headers.get("Authorization")
        await ws.send(json.dumps({"type": "Begin", "id": "s1", "expires_at": 1}))
        async for msg in ws:
            if isinstance(msg, bytes):
                seen["audio"] = len(msg)
                await ws.send(json.dumps(turn(0, [("hi", 0.9)], end=True)))
            elif json.loads(msg)["type"] == "Terminate":
                await ws.send(json.dumps({"type": "Termination"}))
                return

    messages: list = []
    _, info = asyncio.run(_run(handler, messages))
    assert info.clean
    assert seen["auth"] == "test-key"
    assert seen["path"].startswith("/v3/ws?") and "speech_model=universal-3-5-pro" in seen["path"]
    assert seen["audio"] == 3200
    assert [type(m) for m in messages] == [AaiBegin, AaiTurn, AaiTermination]


def test_real_connector_reports_close_code_on_drop():
    async def handler(ws):
        await ws.send(json.dumps({"type": "Begin", "id": "s1", "expires_at": 1}))
        await ws.close(code=4001, reason="Not Authorized")

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            settings = replace(TEST_SETTINGS, streaming_host=f"ws://127.0.0.1:{port}")

            async def on_message(m):
                pass

            client = AssemblyAIStreamClient(settings, on_message)
            await client.open()
            return await asyncio.wait_for(client.wait_closed(), 5)

    info = asyncio.run(main())
    assert not info.clean and info.code == 4001 and info.fatal


def test_real_connector_handshake_rejection_is_fatal():
    from http import HTTPStatus

    from app.assemblyai_stream import UpstreamConnectError

    def reject(connection, request):
        return connection.respond(HTTPStatus.UNAUTHORIZED, "Invalid API key\n")

    async def handler(ws):  # never reached
        pass

    async def main():
        async with serve(handler, "127.0.0.1", 0, process_request=reject) as server:
            port = server.sockets[0].getsockname()[1]
            settings = replace(TEST_SETTINGS, streaming_host=f"ws://127.0.0.1:{port}")

            async def on_message(m):
                pass

            with pytest.raises(UpstreamConnectError) as err:
                await AssemblyAIStreamClient(settings, on_message).open()
            return err.value

    err = asyncio.run(main())
    assert err.code == 401 and err.fatal
