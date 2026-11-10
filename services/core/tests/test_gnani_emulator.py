"""Deterministic protocol faults, without contacting a real provider."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from gnani_emulator import Stats, add_seeded_noise, create_app, decode, encode_clip


def test_seeded_noise_preserves_marked_transcript() -> None:
    first = encode_clip("answer", noise_seed=9)
    assert first == encode_clip("answer", noise_seed=9)
    assert first != encode_clip("answer", noise_seed=10)
    assert decode(first) == "answer"
    noisy = add_seeded_noise(first, 9)
    assert noisy == add_seeded_noise(first, 9)
    assert noisy != first
    assert decode(noisy) == "answer"


def test_partial_and_malformed_precede_final() -> None:
    for fault in ("partial", "malformed"):
        with (
            TestClient(create_app(Stats(fault=fault))) as client,
            client.websocket_connect("/stt/v3/stream") as ws,
        ):
            ws.receive_json()
            ws.send_bytes(encode_clip("answer"))
            ws.receive_json()
            ws.send_json({"type": "commit"})
            ws.receive_json()
            extra = ws.receive_text()
            if fault == "partial":
                import json

                assert json.loads(extra)["is_final"] is False
            else:
                assert extra == "{"
            assert ws.receive_json()["text"] == "answer"


def test_drop_is_one_shot() -> None:
    with TestClient(create_app(Stats(fault="drop"))) as client:
        with client.websocket_connect("/stt/v3/stream") as ws:
            ws.receive_json()
            ws.send_json({"type": "commit"})
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
            assert exc_info.value.code == 1011
        with client.websocket_connect("/stt/v3/stream") as ws:
            ws.receive_json()
            ws.send_bytes(encode_clip("answer"))
            ws.receive_json()
            ws.send_json({"type": "commit"})
            ws.receive_json()
            assert ws.receive_json()["text"] == "answer"


def test_http_faults_are_one_shot() -> None:
    for fault, code in (("429", 429), ("5xx", 503)):
        with TestClient(create_app(Stats(fault=fault))) as client:
            assert client.post("/api/v1/tts/inference").status_code == code
            assert client.post("/api/v1/tts/inference").status_code == 200
