"""Typed Jev-style player for the game's seat-visible semantic state.

The model request runs off the simulator clock. Each step still receives an
immediate action with the matching request ID, using the latest validated
choice. The private journal retains request and answer provenance.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

import websockets
from pydantic import BaseModel, ValidationError

from cogsguard.semantic.systemone import action_request, selected_action
from cogsguard.semantic.wire import PlayerConfig, PlayerObservation, build_player_state


class TypedPlayerConfig(PlayerConfig):
    action_names: list[str]


class FinalMessage(BaseModel):
    type: Literal["final"]


class SystemOnePlayer:
    def __init__(
        self, *, endpoint: str, model: str, key: str | None = None,
        interval_steps: int = 24, trace_path: Path | None = None,
    ) -> None:
        if interval_steps < 1:
            raise ValueError("interval_steps must be positive")
        self.endpoint = endpoint
        self.model = model
        self.key = key
        self.interval_steps = interval_steps
        self.config: TypedPlayerConfig | None = None
        self.choice = "noop"
        self.choice_request_step: int | None = None
        self.model_task: asyncio.Task[dict] | None = None
        self.last_requested_step = -interval_steps
        self.active_request_step: int | None = None
        self.trace = None
        if trace_path is not None:
            descriptor = os.open(trace_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self.trace = os.fdopen(descriptor, "w", encoding="utf-8")

    def close(self) -> None:
        if self.trace is not None:
            self.trace.close()

    def record(self, event: dict) -> None:
        if self.trace is not None:
            self.trace.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
            self.trace.flush()

    def configure(self, raw: dict) -> None:
        self.config = TypedPlayerConfig.model_validate(raw)
        if "noop" not in self.config.action_names:
            raise ValueError("SystemOne player requires the game's noop action")

    def request(self, body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.key is not None:
            headers["Authorization"] = f"Bearer {self.key}"
        request = urllib.request.Request(
            self.endpoint, data=json.dumps(body).encode(), headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    async def action_for_observation(self, raw: dict) -> dict:
        message = PlayerObservation.model_validate(raw)
        assert self.config is not None
        state = build_player_state(self.config, message)
        if self.model_task is not None and self.model_task.done():
            try:
                response = self.model_task.result()
                answer = selected_action(response, self.config.action_names)
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, ValidationError) as error:
                self.choice = "noop"
                self.choice_request_step = None
                self.record({"type": "model_error", "request_step": self.active_request_step,
                             "error": str(error)})
            else:
                self.choice = answer.choice
                self.choice_request_step = self.active_request_step
                self.record({"type": "model_answer", "request_step": self.active_request_step,
                             "response": response, "selected_action": self.choice})
            self.model_task = None
        if self.model_task is None and message.step - self.last_requested_step >= self.interval_steps:
            body = action_request(state, self.config.action_names, self.model)
            self.last_requested_step = message.step
            self.active_request_step = message.step
            self.record({"type": "model_request", "step": message.step, "request": body})
            self.model_task = asyncio.create_task(asyncio.to_thread(self.request, body))
        action = {
            "type": "action", "action_name": self.choice,
            "request_id": f"step-{message.step}",
            "policy_infos": {"policy_name": "systemone-semantic",
                             "choice_request_step": self.choice_request_step},
        }
        self.record({"type": "submitted_action", "step": message.step,
                     "action": self.choice, "choice_request_step": self.choice_request_step,
                     "observation": state.model_dump(mode="json")})
        return action


async def run_systemone_player(*, player_ws_url: str, player: SystemOnePlayer) -> None:
    try:
        async with websockets.connect(player_ws_url, max_size=None) as websocket:
            async for raw_message in websocket:
                message = json.loads(raw_message)
                if message["type"] == "player_config":
                    player.configure(message)
                elif message["type"] == "observation":
                    await websocket.send(json.dumps(await player.action_for_observation(message)))
                elif message["type"] == "final":
                    FinalMessage.model_validate(message)
                    return
    finally:
        player.close()


def main() -> None:
    base = os.environ.get("AWS_ENDPOINT_URL_BEDROCK_RUNTIME")
    endpoint = os.environ.get("COGAME_SYSTEMONE_URL") or (
        base.rstrip("/") + "/v1/systemone" if base else None
    )
    if endpoint is None:
        raise ValueError("COGAME_SYSTEMONE_URL or AWS_ENDPOINT_URL_BEDROCK_RUNTIME is required")
    player = SystemOnePlayer(
        endpoint=endpoint,
        model=os.environ.get("COGAME_SYSTEMONE_MODEL", "typesafe/jev-1.13"),
        key=os.environ.get("COGAME_SYSTEMONE_KEY"),
        interval_steps=int(os.environ.get("COGAME_SYSTEMONE_INTERVAL_STEPS", "24")),
        trace_path=Path(os.environ["COGAME_DECISION_TRACE"]) if "COGAME_DECISION_TRACE" in os.environ else None,
    )
    asyncio.run(run_systemone_player(player_ws_url=os.environ["COWORLD_PLAYER_WS_URL"], player=player))


if __name__ == "__main__":
    main()
