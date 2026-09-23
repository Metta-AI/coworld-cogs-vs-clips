"""Decode the seat-visible Coworld player wire into the game semantic state."""

from __future__ import annotations

from typing import Literal

from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.sdk.agent import MettagridState
from mettagrid.simulator import AgentObservation
from mettagrid.simulator.interface import Location, ObservationToken, VisibleTalk
from pydantic import BaseModel

from cogsguard.semantic.surface import CogsguardSemanticSurface


class PlayerConfig(BaseModel):
    type: Literal["player_config"]
    protocol: Literal["coworld.player.v1"]
    mission: str
    slot: int
    policy_env: PolicyEnvInterface


class WireVisibleTalk(BaseModel):
    agent_id: int
    text: str
    row: int
    col: int
    remaining_steps: int


class PlayerObservation(BaseModel):
    type: Literal["observation"]
    protocol: Literal["coworld.player.v1"]
    mission: str
    slot: int
    step: int
    observation: list[tuple[int, int, int]]
    visible_talk: list[WireVisibleTalk]


def decode_player_observation(
    config: PlayerConfig, message: PlayerObservation
) -> AgentObservation:
    if config.slot != message.slot or config.mission != message.mission:
        raise ValueError(
            "Player observation does not match configured seat and mission"
        )
    features = {feature.id: feature for feature in config.policy_env.obs_features}
    tokens = [
        ObservationToken(
            feature=features[feature_id],
            value=value,
            raw_token=(location, feature_id, value),
        )
        for location, feature_id, value in message.observation
        if location != 255 and feature_id != 255
    ]
    talk = [
        VisibleTalk(
            agent_id=item.agent_id,
            text=item.text,
            location=Location(item.row, item.col),
            remaining_steps=item.remaining_steps,
        )
        for item in message.visible_talk
    ]
    return AgentObservation(agent_id=message.slot, tokens=tokens, talk=talk)


def build_cogsguard_state(
    config: PlayerConfig, message: PlayerObservation
) -> MettagridState:
    if config.mission != "cogsguard":
        raise ValueError(
            f"Cogsguard semantic state is unavailable for mission {config.mission!r}"
        )
    return CogsguardSemanticSurface().build_state(
        decode_player_observation(config, message),
        policy_env_info=config.policy_env,
        step=message.step,
    )
