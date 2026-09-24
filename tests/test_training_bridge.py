from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "coworld" / "game"))
from training_bridge import TrainingSession  # noqa: E402


@pytest.mark.parametrize(
    "variant,players",
    [("certification", 8), ("machina-1-daily", 8), ("four-score-daily", 32)],
)
def test_complete_game_uses_published_seat_observations(
    variant: str, players: int
) -> None:
    session = TrainingSession(variant, steps=2)
    observation = session.reset({"seed": "test-seed", "players": players})
    initial_scores = session.game.scores()
    for turn in range(2 * players):
        assert observation["kind"] == "decision"
        assert observation["seat"] == turn % players
        assert (
            observation["semantic_view"]["observation"]
            == session.game.episode.observation_message(turn % players)["observation"]
        )
        encoding = session.encode()
        assert len(encoding["values"]) == 1502
        assert encoding["actions"] == [
            {"action_name": action} for action in session.game.episode.action_names
        ]
        result = session.step(
            {"decision_id": turn, "response": session.teacher()["response"]}
        )
        assert result["kind"] == "accepted"
        observation = result["observation"]
    assert observation == {
        "kind": "terminal",
        "scores": dict(enumerate(session.game.scores())),
    }
    assert session.game.sim.current_step == 2
    assert initial_scores == [0.0] * players


def test_rejected_action_does_not_advance_game() -> None:
    session = TrainingSession("certification", steps=2)
    session.reset({"seed": "test-seed", "players": 8})
    assert (
        session.step(
            {"decision_id": 1, "response": json.dumps({"action_name": "noop"})}
        )["kind"]
        == "rejected"
    )
    assert (
        session.step(
            {"decision_id": 0, "response": json.dumps({"action_name": "invalid"})}
        )["kind"]
        == "rejected"
    )
    assert session.decision_id == 0
    assert session.game.sim.current_step == 0
