from __future__ import annotations

import pytest
from voice_bot_common import decode_synthetic_pcm, encode_synthetic_pcm


@pytest.mark.parametrize(
    "text",
    ["yes", "no", "on", "off", "green", "amber", "red", "up", "tripped"],
)
def test_synthetic_pcm_carries_exact_answer_text(text: str) -> None:
    pcm = encode_synthetic_pcm(text)

    assert len(pcm) >= 3200
    assert len(pcm) % 1024 == 0
    assert decode_synthetic_pcm(pcm) == text


def test_synthetic_pcm_rejects_unmarked_audio() -> None:
    with pytest.raises(ValueError, match="load-test marker"):
        decode_synthetic_pcm(b"\x00\x00" * 2000)


def test_synthetic_pcm_keeps_answer_after_early_barge_in_frame() -> None:
    answer = encode_synthetic_pcm("stuck connecting")

    assert decode_synthetic_pcm(b"\x00\x00" * 256 + answer) == "stuck connecting"
