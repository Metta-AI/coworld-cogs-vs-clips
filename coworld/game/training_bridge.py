"""Cogs vs Clips decisions over the shared Metta JSONL training protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from server import CogsVsClipsGame

ROOT = Path(__file__).resolve().parents[2]
OBSERVATION_TOKENS = 500


class TrainingSession:
    def __init__(self, variant: str, steps: int | None) -> None:
        manifest = json.loads((ROOT / "coworld_manifest_template.json").read_text())
        if variant == "certification":
            self.config = manifest["certification"]["game_config"]
        else:
            self.config = next(
                entry["game_config"]
                for entry in manifest["variants"]
                if entry["id"] == variant
            )
        if steps is not None:
            if not 1 <= steps <= 10000:
                raise ValueError("Steps must be between 1 and 10000")
            self.config = {**self.config, "max_steps": steps}
        self.players = len(self.config["players"])

    def reset(self, request: dict[str, object]) -> dict[str, object]:
        if int(request["players"]) != self.players:
            raise ValueError(
                f"{self.config['mission']} requires {self.players} players"
            )
        seed = int.from_bytes(
            hashlib.sha256(str(request["seed"]).encode()).digest()[:4], "big"
        )
        config = {
            **self.config,
            "seed": seed,
            "tokens": [f"training-{slot}" for slot in range(self.players)],
        }
        self.game = CogsVsClipsGame(
            config, Path("/tmp/cvc-training-results.json"), None, lambda: None
        )
        self.decision_id = 0
        self.actions: list[str] = []
        self.inbox: list[dict[str, object]] = []
        return self.observation()

    def observation(self) -> dict[str, object]:
        if self.game.sim.is_done():
            return {"kind": "terminal", "scores": dict(enumerate(self.game.scores()))}
        seat = len(self.actions)
        wire = self.game.episode.observation_message(seat)
        visible = {
            "mission": self.config["mission"],
            "step": self.game.sim.current_step,
            **wire,
        }
        action_names = self.game.episode.action_names
        candidates = {
            name: {"decision": {"action_name": name}, "criterion": name}
            for name in action_names
        }
        return {
            "kind": "decision",
            "game": "cogs_vs_clips",
            "decision_id": self.decision_id,
            "seat": seat,
            "engine_seat": seat,
            "turn": self.game.sim.current_step,
            "semantic_view": visible,
            "inbox": self.inbox,
            "messages": [
                {
                    "role": "system",
                    "content": "Choose one legal Cogs vs Clips action for this seat.",
                },
                {"role": "user", "content": json.dumps(visible, separators=(",", ":"))},
            ],
            "speech_messages": [],
            "action_schema": {
                "type": "object",
                "properties": {"action_name": {"type": "string", "enum": action_names}},
                "required": ["action_name"],
            },
            "typed_question": {
                "state": visible,
                "instructions": "Choose a legal movement or noop action.",
                "candidates": candidates,
            },
        }

    def encode(self) -> dict[str, object]:
        seat = len(self.actions)
        wire = self.game.episode.observation_message(seat)
        tokens = wire["observation"]
        if len(tokens) != OBSERVATION_TOKENS:
            raise ValueError(
                f"Expected {OBSERVATION_TOKENS} seat-visible tokens, got {len(tokens)}"
            )
        return {
            "decision_id": self.decision_id,
            "values": [
                seat / self.players,
                self.game.sim.current_step / self.config["max_steps"],
            ]
            + [value / 255 for token in tokens for value in token],
            "actions": [
                {"action_name": name} for name in self.game.episode.action_names
            ],
        }

    def teacher(self) -> dict[str, str]:
        return {"response": json.dumps({"action_name": "noop"})}

    def step(self, request: dict[str, object]) -> dict[str, object]:
        if request["decision_id"] != self.decision_id:
            return {"kind": "rejected", "reason": "stale decision"}
        response = json.loads(str(request["response"]))
        if (
            not isinstance(response, dict)
            or response.get("action_name") not in self.game.episode.action_names
        ):
            return {"kind": "rejected", "reason": "unknown action"}
        action = response["action_name"]
        self.actions.append(action)
        self.decision_id += 1
        if len(self.actions) == self.players:
            for seat, selected in enumerate(self.actions):
                self.game.sim.agent(seat).set_action(selected)
            self.game.sim.step()
            self.actions = []
        return {
            "kind": "accepted",
            "action": {"action_name": action},
            "observation": self.observation(),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant",
        choices=("certification", "machina-1-daily", "four-score-daily"),
        default="certification",
    )
    parser.add_argument("--steps", type=int)
    args = parser.parse_args()
    session = TrainingSession(args.variant, args.steps)
    for line in sys.stdin:
        request = json.loads(line)
        match request["kind"]:
            case "reset":
                response = session.reset(request)
            case "encode":
                response = session.encode()
            case "teacher":
                response = session.teacher()
            case "step":
                response = session.step(request)
            case _:
                raise ValueError(f"Unknown training command {request['kind']}")
        print(json.dumps(response, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
