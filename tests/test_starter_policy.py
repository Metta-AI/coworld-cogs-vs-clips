"""The game-owned scripted teacher must run against current CogsGuard observations."""

from contextlib import closing

import pytest

from cogsguard.missions.machina_1 import make_machina1_mission
from cogsguard.policy.starter import (
    MOVE_DELTAS,
    StarterCogPolicyImpl,
    StarterCogState,
    StarterPolicy,
)
from mettagrid.policy.loader import initialize_or_load_policy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.policy.policy_spec import PolicySpec
from mettagrid.simulator import Simulation


def test_starter_teacher_moves_and_aligns_current_machina_game() -> None:
    config = make_machina1_mission(num_agents=8).make_env()
    config.game.max_steps = 128
    info = PolicyEnvInterface.from_mg_cfg(config)
    policy = initialize_or_load_policy(
        info, PolicySpec(class_path="cogsguard.policy.starter.StarterPolicy")
    )
    assert isinstance(policy, StarterPolicy)
    agents = [policy.agent_policy(seat) for seat in range(info.num_agents)]
    movements = 0
    with closing(Simulation(config, seed=73)) as sim:
        policy.reset()
        for agent in agents:
            agent.reset(sim)
        for _ in range(config.game.max_steps):
            for seat, agent in enumerate(agents):
                action = agent.step(sim.agent(seat).observation)
                movements += action.name.startswith("move_")
                sim.agent(seat).set_action(action)
            sim.step()
            if sim.is_done():
                break
        assert movements > 128
        assert sim._c_sim.get_game_stat("cogs/aligned.junction.held") > 0


def test_remembered_junction_route_goes_around_a_wall() -> None:
    policy = object.__new__(StarterCogPolicyImpl)
    policy._center = (6, 6)
    state = StarterCogState(explore_direction_index=0)
    state.blocked = {(0, 1), (0, 2), (1, 1), (1, 2)}
    target = (0, 3)
    state.seen_tags_by_position = {
        position: set() for position in (*state.blocked, state.position, target)
    }

    for _ in range(7):
        direction = policy._route_to_remembered_junction(target, {}, state)
        assert direction is not None
        delta = MOVE_DELTAS[direction]
        state.position = (state.position[0] + delta[0], state.position[1] + delta[1])
        if state.position == target:
            break

    assert state.position == target


@pytest.mark.parametrize(
    "name",
    ["MinerRolePolicy", "ScoutRolePolicy", "AlignerRolePolicy", "ScramblerRolePolicy"],
)
def test_fixed_role_teachers_load_from_policy_specs(name: str) -> None:
    config = make_machina1_mission(num_agents=8).make_env()
    info = PolicyEnvInterface.from_mg_cfg(config)
    policy = initialize_or_load_policy(
        info, PolicySpec(class_path=f"cogsguard.policy.starter.{name}")
    )
    with closing(Simulation(config, seed=73)) as sim:
        agent = policy.agent_policy(0)
        agent.reset(sim)
        assert agent.step(sim.agent(0).observation).name in info.action_names
