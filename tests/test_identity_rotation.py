"""TeamIdentityRotation relabels identity observation values, and only those, per episode."""

from __future__ import annotations

import numpy as np

from cogsguard.game.teams.identity_rotation import TeamIdentityRotation, team_names_by_id
from cogsguard.missions.four_score import FourScoreMission
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Simulation, Simulator

EMPTY_TOKEN = 0xFF


def _four_score_env(seed: int) -> MettaGridConfig:
    env = FourScoreMission().make_env()
    env.game.map_builder.seed = seed
    return env


def _expected_lookups(env: MettaGridConfig, sim: Simulation, rotation: TeamIdentityRotation) -> dict[int, np.ndarray]:
    """Feature id -> value table, written out independently of the handler's own construction."""
    team_names = team_names_by_id(env)
    tag_ids = {name: tag_id for tag_id, name in PolicyEnvInterface.from_mg_cfg(env).tag_id_to_name.items()}
    features = {feature.name: int(feature.id) for feature in sim.features}
    tags, groups, agent_ids = np.arange(256), np.arange(256), np.arange(256)
    for team, name in enumerate(team_names):
        image = rotation.team_permutation[team]
        groups[team] = image
        for family in ("team:", "net:"):
            tags[tag_ids[family + name]] = tag_ids[family + team_names[image]]
    agent_ids[: len(rotation.agent_id_permutation)] = rotation.agent_id_permutation
    return {features["tag"]: tags, features["agent:group"]: groups, features["agent_id"]: agent_ids}


def _step_both(sims: tuple[Simulation, Simulation], rng: np.random.Generator) -> None:
    actions = rng.choice(sims[0].action_names, size=sims[0].num_agents)
    for sim in sims:
        for agent, action in enumerate(actions):
            sim.agent(agent).set_action(str(action))
        sim.step()


def test_team_names_follow_engine_team_ids() -> None:
    assert team_names_by_id(_four_score_env(1)) == ["cogs_red", "cogs_blue", "cogs_green", "cogs_yellow"]


def test_rotation_rewrites_identity_values_and_leaves_everything_else_alone() -> None:
    env = _four_score_env(3)
    plain = Simulator().new_simulation(env, seed=3)
    rotation = TeamIdentityRotation(seed=7)
    simulator = Simulator()
    simulator.add_event_handler(rotation)
    rotated = simulator.new_simulation(env, seed=3)
    assert rotation.team_permutation != sorted(rotation.team_permutation)
    assert rotation.agent_id_permutation != sorted(rotation.agent_id_permutation)

    lookups = _expected_lookups(env, plain, rotation)
    rng = np.random.default_rng(0)
    for _ in range(6):
        engine, seen = plain._c_sim.observations(), rotated._c_sim.observations()
        assert np.array_equal(engine[:, :, :2], seen[:, :, :2])
        expected = engine[:, :, 2].copy()
        live = engine[:, :, 0] != EMPTY_TOKEN
        for feature_id, table in lookups.items():
            hit = live & (engine[:, :, 1] == feature_id)
            expected[hit] = table[engine[:, :, 2][hit]]
        assert np.array_equal(seen[:, :, 2], expected)
        assert np.array_equal(plain.episode_rewards, rotated.episode_rewards)
        _step_both((plain, rotated), rng)


def test_permutations_hold_for_an_episode_and_are_redrawn_for_the_next() -> None:
    env = _four_score_env(1)
    rotation = TeamIdentityRotation(seed=0)
    simulator = Simulator()
    simulator.add_event_handler(rotation)
    drawn = set()
    for episode in range(5):
        sim = simulator.new_simulation(env, seed=episode)
        at_start = (tuple(rotation.team_permutation), tuple(rotation.agent_id_permutation))
        for _ in range(3):
            for agent in range(sim.num_agents):
                sim.agent(agent).set_action("noop")
            sim.step()
        assert (tuple(rotation.team_permutation), tuple(rotation.agent_id_permutation)) == at_start
        assert sorted(at_start[0]) == [0, 1, 2, 3]
        assert sorted(at_start[1]) == list(range(32))
        drawn.add(at_start)
        sim.close()
    assert len(drawn) > 1


def test_seeded_rotation_is_reproducible_and_independent_across_simulation_seeds() -> None:
    def first_permutations(rotation_seed: int, sim_seed: int) -> tuple:
        rotation = TeamIdentityRotation(seed=rotation_seed)
        simulator = Simulator()
        simulator.add_event_handler(rotation)
        simulator.new_simulation(_four_score_env(2), seed=sim_seed).close()
        return tuple(rotation.team_permutation), tuple(rotation.agent_id_permutation)

    assert first_permutations(5, 0) == first_permutations(5, 0)
    assert first_permutations(5, 0) != first_permutations(5, 1)
