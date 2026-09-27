"""M1: AssemblyAI streaming relay, tested offline against a fake upstream."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import ws_session
from app.assemblyai_stream import UpstreamConnectError, build_stream_url
from app.config import Settings
from app.main import app
from app.models import AaiError, AaiOther, AaiTurn, parse_aai_message
from app.ws_session import confidence_band

from .fake_upstream import FakeClosed, FakeConnector, FakeUpstream, turn

TEST_SETTINGS = replace(
    Settings(),
    assemblyai_api_key="test-key",
    streaming_speech_model="universal-3-5-pro",
    streaming_sample_rate=16000,
    end_of_turn_confidence_threshold=None,
    min_turn_silence_ms=None,
    max_turn_silence_ms=None,
    upstream_reconnect_backoff_s=0.01,
    upstream_terminate_timeout_s=1.0,
)
AUDIO = b"\x00\x00" * 1600  # 100 ms of 16 kHz PCM16 silence


@pytest.fixture
def use_connector():
    def _use(connector, settings: Settings = TEST_SETTINGS):
        ws_session.connector_override = connector
        ws_session.settings_override = settings
        return connector

    yield _use
    ws_session.connector_override = None
    ws_session.settings_override = None


def recv_until(ws, predicate, limit: int = 20) -> list[dict]:
    """Collect events until one satisfies predicate; return all collected."""
    seen = []
    for _ in range(limit):
        event = json.loads(ws.receive_text())
        seen.append(event)
        if predicate(event):
            return seen
    raise AssertionError(f"predicate never matched; saw {seen}")


def is_state(name):
    return lambda e: e["type"] == "state" and e["state"] == name


# -- pure units ---------------------------------------------------------------


def test_stream_url_has_required_params_and_omits_unset_tuning():
    url = urlparse(build_stream_url(TEST_SETTINGS))
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert (url.scheme, url.netloc, url.path) == ("wss", "streaming.assemblyai.com", "/v3/ws")
    assert q == {
        "sample_rate": "16000",
        "encoding": "pcm_s16le",
        "speech_model": "universal-3-5-pro",
        "format_turns": "true",
    }


def test_stream_url_includes_turn_tuning_when_configured():
    s = replace(TEST_SETTINGS, end_of_turn_confidence_threshold=0.5, min_turn_silence_ms=500, max_turn_silence_ms=2000)
    q = parse_qs(urlparse(build_stream_url(s)).query)
    assert q["end_of_turn_confidence_threshold"] == ["0.5"]
    assert q["min_turn_silence"] == ["500"]
    assert q["max_turn_silence"] == ["2000"]


def test_parse_messages():
    t = parse_aai_message(turn(3, [("gate", 0.92), ("fifteen", 0.41)], end=True))
    assert isinstance(t, AaiTurn) and t.turn_order == 3 and t.words[1].confidence == 0.41
    assert isinstance(parse_aai_message({"type": "Error", "error_code": 3007, "error": "chunk"}), AaiError)
    assert isinstance(parse_aai_message({"type": "SpeechStarted", "timestamp": 10}), AaiOther)
    # unknown extra fields are tolerated
    extra = turn(1, [("hi", 0.9)], end=False) | {"speaker_label": "A", "language_code": "en"}
    assert isinstance(parse_aai_message(extra), AaiTurn)


@pytest.mark.parametrize("conf,band", [(0.85, "high"), (0.99, "high"), (0.84, "mid"), (0.6, "mid"), (0.59, "low"), (0.0, "low")])
def test_confidence_band_edges(conf, band):
    assert confidence_band(conf, TEST_SETTINGS) == band


# -- end to end through the browser WebSocket ---------------------------------


def test_partials_and_final_turn_flow_to_browser(use_connector):
    fake = FakeUpstream(
        script=[
            [turn(0, [("meet", 0.95), ("priya", 0.7)], end=False)],
            [
                turn(0, [("meet", 0.95), ("priya", 0.7), ("fifteen", 0.4)], end=True),
                turn(0, [("Meet", 0.95), ("Priya", 0.7), ("15.", 0.4)], end=True, formatted=True),
            ],
        ]
    )
    connector = use_connector(FakeConnector(fake))
    client = TestClient(app)
    with client.websocket_connect("/ws/session/abc") as ws:
        first = json.loads(ws.receive_text())
        assert (first["type"], first["state"]) == ("state", "idle") and first["ts"] > 0
        ws.send_text(json.dumps({"type": "start_stream"}))
        recv_until(ws, is_state("listening"))

        ws.send_bytes(AUDIO)
        partial = recv_until(ws, lambda e: e["type"] == "partial_transcript")[-1]
        assert partial["text"] == "meet priya"
        assert [w["band"] for w in partial["words"]] == ["high", "mid"]

        ws.send_bytes(AUDIO)
        finals = [recv_until(ws, lambda e: e["type"] == "final_turn")[-1]]
        finals.append(recv_until(ws, lambda e: e["type"] == "final_turn")[-1])
        assert [f["formatted"] for f in finals] == [False, True]
        assert {(f["stream_id"], f["turn_order"]) for f in finals} == {("sess-fake", 0)}
        assert finals[1]["text"] == "Meet Priya 15."
        assert finals[1]["words"][2]["band"] == "low"

        ws.send_text(json.dumps({"type": "end_session"}))
        recv_until(ws, is_state("stopped"))

    assert fake.sent_audio == [AUDIO, AUDIO]
    assert fake.sent_control == [{"type": "Terminate"}]  # clean shutdown
    assert fake.headers["Authorization"] == "test-key"
    assert connector.connections == [fake]


def test_stop_stream_terminates_but_keeps_browser_socket(use_connector):
    fake, second = FakeUpstream(), FakeUpstream()
    connector = use_connector(FakeConnector(fake, second))
    with TestClient(app).websocket_connect("/ws/session/abc") as ws:
        ws.send_text(json.dumps({"type": "start_stream"}))
        recv_until(ws, is_state("listening"))
        ws.send_text(json.dumps({"type": "stop_stream"}))
        recv_until(ws, is_state("stopped"))
        assert fake.sent_control == [{"type": "Terminate"}]
        # can start again on the same browser socket
        ws.send_text(json.dumps({"type": "start_stream"}))
        recv_until(ws, is_state("listening"))
    assert connector.connections == [fake, second]


def test_reconnects_after_unexpected_upstream_drop(use_connector):
    dropping = FakeUpstream(script=[FakeClosed(1011, "internal error")])
    healthy = FakeUpstream(script=[[turn(0, [("hello", 0.9)], end=True)]])
    connector = use_connector(FakeConnector(dropping, healthy))
    with TestClient(app).websocket_connect("/ws/session/abc") as ws:
        ws.send_text(json.dumps({"type": "start_stream"}))
        recv_until(ws, is_state("listening"))
        ws.send_bytes(AUDIO)  # triggers the drop
        events = recv_until(ws, is_state("listening"))
        errors = [e for e in events if e["type"] == "error"]
        assert errors and errors[0]["recoverable"] is True and errors[0]["code"] == 1011
        assert any(e["type"] == "state" and e["state"] == "reconnecting" for e in events)
        ws.send_bytes(AUDIO)
        final = recv_until(ws, lambda e: e["type"] == "final_turn")[-1]
        assert final["text"] == "hello"
        ws.send_text(json.dumps({"type": "end_session"}))
        recv_until(ws, is_state("stopped"))
    assert len(connector.connections) == 2
    assert healthy.sent_control == [{"type": "Terminate"}]


def test_auth_failure_is_fatal_and_not_retried(use_connector):
    connector = use_connector(FakeConnector(UpstreamConnectError("Not Authorized", code=4001), FakeUpstream()))
    with TestClient(app).websocket_connect("/ws/session/abc") as ws:
        ws.send_text(json.dumps({"type": "start_stream"}))
        events = recv_until(ws, is_state("stopped"))
        errors = [e for e in events if e["type"] == "error"]
        assert len(errors) == 1 and errors[0]["recoverable"] is False
    assert connector.connections == []  # second item never used


def test_missing_api_key_reports_error_without_connecting(use_connector):
    connector = use_connector(FakeConnector(FakeUpstream()), replace(TEST_SETTINGS, assemblyai_api_key=""))
    with TestClient(app).websocket_connect("/ws/session/abc") as ws:
        ws.send_text(json.dumps({"type": "start_stream"}))
        events = recv_until(ws, is_state("stopped"))
        assert "ASSEMBLYAI_API_KEY" in [e for e in events if e["type"] == "error"][0]["message"]
    assert connector.connections == []


def test_gives_up_after_max_reconnect_attempts(use_connector):
    s = replace(TEST_SETTINGS, upstream_max_reconnect_attempts=2)
    use_connector(FakeConnector(*[UpstreamConnectError("timeout") for _ in range(3)]), s)
    with TestClient(app).websocket_connect("/ws/session/abc") as ws:
        ws.send_text(json.dumps({"type": "start_stream"}))
        events = recv_until(ws, is_state("stopped"))
        flags = [e["recoverable"] for e in events if e["type"] == "error"]
        assert flags == [True, True, False]


def test_browser_disconnect_terminates_upstream(use_connector):
    fake = FakeUpstream()
    use_connector(FakeConnector(fake))
    with TestClient(app).websocket_connect("/ws/session/abc") as ws:
        ws.send_text(json.dumps({"type": "start_stream"}))
        recv_until(ws, is_state("listening"))
    deadline = time.time() + 3
    while not fake.sent_control and time.time() < deadline:
        time.sleep(0.02)
    assert fake.sent_control == [{"type": "Terminate"}]


def test_invalid_control_message_is_reported(use_connector):
    use_connector(FakeConnector())
    with TestClient(app).websocket_connect("/ws/session/abc") as ws:
        ws.receive_text()  # idle
        ws.send_text(json.dumps({"type": "nope"}))
        event = json.loads(ws.receive_text())
        assert event["type"] == "error" and event["recoverable"] is True


def test_health_does_not_leak_key():
    body = TestClient(app).get("/api/health").json()
    assert body["status"] == "ok"
    assert "test-key" not in json.dumps(body)


def test_public_config_exposes_bands_only():
    body = TestClient(app).get("/api/config").json()
    assert body == {
        "conf_band_high": 0.85,
        "conf_band_low": 0.6,
        "pause_min_ms": 250,
        "long_pause_min_ms": 1000,
        "low_conf_threshold": 0.6,
    }


def test_final_turn_carries_features_and_repetition_uses_previous_distinct_turn(use_connector):
    first = [("gate", 0.9), ("fifteen", 0.4)]
    fake = FakeUpstream(
        script=[
            [turn(0, first, end=True), turn(0, [("Gate", 0.9), ("15.", 0.4)], end=True, formatted=True)],
            [turn(1, first, end=True), turn(1, [("Gate", 0.9), ("fifteen.", 0.4)], end=True, formatted=True)],
        ]
    )
    use_connector(FakeConnector(fake))
    with TestClient(app).websocket_connect("/ws/session/abc") as ws:
        ws.send_text(json.dumps({"type": "start_stream"}))
        recv_until(ws, is_state("listening"))
        ws.send_bytes(AUDIO)
        t0 = [recv_until(ws, lambda e: e["type"] == "final_turn")[-1] for _ in range(2)]
        ws.send_bytes(AUDIO)
        t1 = [recv_until(ws, lambda e: e["type"] == "final_turn")[-1] for _ in range(2)]
        ws.send_text(json.dumps({"type": "end_session"}))
        recv_until(ws, is_state("stopped"))

    f = t0[0]["features"]
    assert f["word_count"] == 2 and f["min_asr_conf"] == pytest.approx(0.4)
    assert f["low_conf_frac"] == pytest.approx(0.5) and f["pause_count"] == 0
    # turn 0 (both versions): nothing before it
    assert [t["features"]["repetition_overlap"] for t in t0] == [None, None]
    # turn 1 repeats turn 0; its formatted re-send still compares against turn 0, not itself
    assert [t["features"]["repetition_overlap"] for t in t1] == [pytest.approx(1.0), pytest.approx(1.0)]
    assert all(t["features"]["is_repetition"] for t in t1)
