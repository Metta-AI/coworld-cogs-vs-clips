"""Per-episode relabelling of team and agent identities in observations.

Team identity reaches a policy as small integers on shared observation channels:
the ``team:<name>`` / ``net:<name>`` tag ids on the ``tag`` feature, the engine
team id on ``agent:group``, and each agent's index on ``agent_id``. Those numbers
are fixed per team and per agent for every episode, so a learned policy can key
behaviour to "the team with the lowest tag id" or to one particular agent index,
and inherit any engine asymmetry that follows the same order.

``TeamIdentityRotation`` removes that. At every episode start it draws a random
permutation of the teams and of the agent indices, and rewrites the matching
observation values on every tick. A permutation holds for the whole episode and
for every observer, so relative identity ("that agent is on my team", "this
junction is held by the team I saw earlier") is preserved; only the labels
change. Engine state, rewards and stats are untouched.

Observers that read their own team from their own cell (as the starter policy
does) stay consistent. Anything that maps observed labels back to team names
(``tag_id_to_name``, the semantic player surface) reports the relabelled team;
results, stats and replays come from engine state and keep the true names.
Four Score runs it in every episode (``four_score_event_handlers``).
"""

from __future__ import annotations

from typing_extensions import override

import numpy as np

from cogsguard.game.teams.team import TeamConfig
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator.interface import SimulatorEventHandler

_TEAM_TAG_PREFIX = TeamConfig(name="").team_tag()
_NET_TAG_PREFIX = TeamConfig(name="").net_tag()


def team_names_by_id(env: MettaGridConfig) -> list[str]:
    """Team names indexed by engine team id, read from the agents' team tags."""
    names: dict[int, str] = {}
    for agent in env.game.agents:
        for tag in agent.tags:
            if tag.startswith(_TEAM_TAG_PREFIX):
                names.setdefault(agent.team_id, tag[len(_TEAM_TAG_PREFIX) :])
    return [names[team_id] for team_id in sorted(names)]


class TeamIdentityRotation(SimulatorEventHandler):
    """Rewrite team tags, ``agent:group`` and ``agent_id`` observation values with per-episode permutations.

    Register it after every handler that reads identity values from, or writes
    tokens into, the observation buffer: it must see the episode's final tokens.
    ``seed`` makes the permutation sequence reproducible; it is mixed with the
    simulation seed, so environments built from one template still draw
    independent sequences.
    """

    def __init__(self, seed: int | None = None) -> None:
        super().__init__()
        self.seed = seed
        self.team_permutation: list[int] = []
        self.agent_id_permutation: list[int] = []
        self._rng: np.random.Generator | None = None
        # New value of every observation token, indexed by its (feature, value)
        # bytes read as one little-endian uint16: feature | value << 8.
        self._values = _identity_values()
        # Views into the simulation's observation buffer (fixed for its lifetime).
        self._pairs: np.ndarray | None = None
        self._observed_values: np.ndarray | None = None

    @override
    def on_episode_start(self) -> None:
        if self._rng is None:
            self._rng = np.random.default_rng(None if self.seed is None else [self.seed, self._sim.seed])
        env = self._sim.config
        team_names = team_names_by_id(env)
        self.team_permutation = [int(i) for i in self._rng.permutation(len(team_names))]
        self.agent_id_permutation = [int(i) for i in self._rng.permutation(env.game.num_agents)]
        self._values = self._build_values(env, team_names)
        # A token is (location, feature, value) bytes, so bytes 1-2 read as one
        # little-endian uint16 index: feature | value << 8.
        obs = self._sim._c_sim.observations()
        self._pairs = obs[:, :, 1:].view("<u2")[:, :, 0]
        self._observed_values = obs[:, :, 2]
        self._relabel()

    @override
    def on_step(self) -> None:
        self._relabel()

    def _build_values(self, env: MettaGridConfig, team_names: list[str]) -> np.ndarray:
        feature_ids = {feature.name: int(feature.id) for feature in self._sim.features}
        tag_ids = {name: int(tag_id) for tag_id, name in PolicyEnvInterface.from_mg_cfg(env).tag_id_to_name.items()}

        team_tags = np.arange(256, dtype=np.uint8)
        groups = np.arange(256, dtype=np.uint8)
        for team_id, name in enumerate(team_names):
            image = self.team_permutation[team_id]
            groups[team_id] = image
            for prefix in (_TEAM_TAG_PREFIX, _NET_TAG_PREFIX):
                src, dst = tag_ids.get(prefix + name), tag_ids.get(prefix + team_names[image])
                if src is not None and dst is not None:
                    team_tags[src] = dst

        agent_ids = np.arange(256, dtype=np.uint8)
        agent_ids[: len(self.agent_id_permutation)] = self.agent_id_permutation

        values = _identity_values()
        for feature, table in (("tag", team_tags), ("agent:group", groups), ("agent_id", agent_ids)):
            if feature in feature_ids:
                values[feature_ids[feature] + 256 * np.arange(256)] = table
        return values

    def _relabel(self) -> None:
        # One gather over the whole buffer; tokens of other features and empty
        # (all-0xFF) slots map to their own value.
        np.take(self._values, self._pairs, out=self._observed_values, mode="clip")


def _identity_values() -> np.ndarray:
    return (np.arange(1 << 16) >> 8).astype(np.uint8)
