"""Voice rehearsal bots read only their own simulator card, including presence labels."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from voice_bot_run import Run


def make_run(tmp_path: Path, **overrides: object) -> Run:
    return Run(
        argparse.Namespace(
            core="http://core.test",
            sim="http://sim.test",
            clips=str(tmp_path),
            human=None,
            attach=None,
            parallel=3,
            play=False,
            timeout=10,
            scenario="S7",
            variant="honest",
            **overrides,
        )
    )


@pytest.mark.parametrize("on_site", [True, False])
async def test_presence_turn_speaks_only_the_label_visible_to_this_participant(
    tmp_path: Path,
    on_site: bool,
) -> None:
    run = make_run(tmp_path)
    run.tokens["p_mahesh"] = {"token": "own-token", "scenario_id": "sc_1"}
    q = {
        "id": "q_1",
        "kind": "challenge",
        "language": "mr",
        "text": "Read the label",
        "action": {
            "participant_id": "p_mahesh",
            "location_id": "IDF2",
            "probe_id": "switch_leds",
            "requires_move": False,
        },
    }
    run.state = AsyncMock(return_value={"pending_questions": [q], "questions_asked": 4})
    requests: list[httpx.Request] = []

    def simulator(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/sim/v1/scenarios/sc_1/view"
        assert request.headers["Authorization"] == "Bearer own-token"
        return httpx.Response(
            200,
            json={
                "location_id": "IDF2" if on_site else "GUARD_DESK",
                "labels": [{"token_id": "idf2_switch_label", "value": "K7Q"}] if on_site else [],
            },
        )

    await run.sim.aclose()
    run.sim = httpx.AsyncClient(
        base_url="http://sim.test", transport=httpx.MockTransport(simulator)
    )
    run.synthesize_answer = AsyncMock(return_value=b"pcm")
    run.speak = AsyncMock()
    try:
        await run.turn(object(), "p_mahesh", "mr", {"question_id": "q_1", "text": q["text"]})
        phrase, language = run.synthesize_answer.call_args.args
        from pramana_core.language.presence import read_code

        assert read_code(phrase) == ("K7Q" if on_site else "")
        assert language == "mr"
        run.speak.assert_awaited_once()
        assert len(requests) == 1  # no movement or privileged read to obtain a missing label
    finally:
        await run.core.aclose()
        await run.sim.aclose()


async def test_bot_failure_cancels_speakers_and_closes_http_clients(tmp_path: Path) -> None:
    run = make_run(tmp_path)
    run._main = AsyncMock(side_effect=RuntimeError("socket failed"))
    try:
        with pytest.raises(RuntimeError, match="socket failed"):
            await run.main()
        assert run.core.is_closed
        assert run.sim.is_closed
        assert not run.tasks
    finally:
        await run.core.aclose()
        await run.sim.aclose()


@pytest.mark.parametrize(
    ("probe", "expected"),
    [
        ("switch_leds", "green"),
        ("nvr_screen", "off"),
        ("closet_light", "off"),
        ("room_socket", "off"),
    ],
)
async def test_adversary_does_not_move_to_read_a_claimed_remote_probe(
    tmp_path: Path,
    probe: str,
    expected: str,
) -> None:
    run = make_run(tmp_path)
    run.args.variant = "adversary"
    run.sim.post = AsyncMock(side_effect=AssertionError("the liar must stay at the desk"))
    try:
        value = await run.observe(
            "p_mahesh",
            {
                "location_id": "IDF2",
                "probe_id": probe,
                "requires_move": True,
            },
        )
        assert value == expected
    finally:
        await run.core.aclose()
        await run.sim.aclose()


@pytest.mark.parametrize(("correct", "sealed"), [(False, True), (True, False)])
def test_verified_status_alone_does_not_pass_rehearsal(correct: bool, sealed: bool) -> None:
    from voice_bot_run import rehearsal_passed

    assert not rehearsal_passed(
        "S1",
        "honest",
        {
            "status": "verified",
            "presence_checks": [],
            "disagreements": [],
        },
        correct=correct,
        sealed=sealed,
        identical=True,
        call_errors=[],
    )
