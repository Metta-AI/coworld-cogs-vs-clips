from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cogsguard.semantic.systemone import action_request, selected_action

PLAYER_PATH = Path(__file__).resolve().parents[1] / "coworld" / "player" / "systemone_player.py"
spec = importlib.util.spec_from_file_location("cvc_systemone_player", PLAYER_PATH)
assert spec is not None and spec.loader is not None
player_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = player_module
spec.loader.exec_module(player_module)


class FakeState:
    def model_dump(self, *, mode: str) -> dict:
        assert mode == "json"
        return {"visible": "only my seat"}


def test_typed_candidates_reject_unconfigured_action() -> None:
    request = action_request(FakeState(), ["noop", "move_north"], "typesafe/jev-1.13")
    assert request["state"] == {"visible": "only my seat"}
    assert set(request["questions"]["action"]["criteria"]) == {"noop", "move_north"}
    assert selected_action(
        {"answers": {"action": {"choice": "move_north", "probabilities": {"noop": 0.1}}}},
        ["noop", "move_north"],
    ).choice == "move_north"
    with pytest.raises(ValueError, match="outside"):
        selected_action({"answers": {"action": {"choice": "fly"}}}, ["noop", "move_north"])


def test_model_reply_is_applied_on_later_step_with_private_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(player_module, "build_player_state", lambda _config, _message: FakeState())
    trace = tmp_path / "decision.jsonl"
    player = player_module.SystemOnePlayer(
        endpoint="http://localhost/systemone", model="typesafe/jev-1.13", trace_path=trace
    )
    player.config = SimpleNamespace(action_names=["noop", "move_north"])
    player.request = lambda _body: {"answers": {"action": {"choice": "move_north"}}}

    async def play() -> tuple[dict, dict]:
        first = await player.action_for_observation(_observation(0))
        assert player.model_task is not None
        await player.model_task
        second = await player.action_for_observation(_observation(1))
        return first, second

    first, second = asyncio.run(play())
    player.close()
    assert first["action_name"] == "noop"
    assert second["action_name"] == "move_north"
    assert second["request_id"] == "step-1"
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    assert [event["type"] for event in events] == [
        "model_request", "submitted_action", "model_answer", "submitted_action"
    ]
    assert events[0]["request"]["state"] == {"visible": "only my seat"}
    assert trace.stat().st_mode & 0o777 == 0o600


def _observation(step: int) -> dict:
    return {
        "type": "observation", "protocol": "coworld.player.v1",
        "mission": "cogsguard", "slot": 0, "step": step,
        "observation": [(254, 1, 7)], "visible_talk": [],
    }
