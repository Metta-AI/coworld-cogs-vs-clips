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
from mettagrid.simulator.interface import AgentObservation, ObservationToken


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


def test_remembered_target_route_goes_around_a_wall() -> None:
    policy = object.__new__(StarterCogPolicyImpl)
    policy._center = (6, 6)
    state = StarterCogState(explore_direction_index=0)
    state.blocked = {(0, 1), (0, 2), (1, 1), (1, 2)}
    target = (0, 3)
    state.seen_tags_by_position = {
        position: set() for position in (*state.blocked, state.position, target)
    }

    for _ in range(7):
        direction = policy._route_to_remembered_target(target, {}, state)
        assert direction is not None
        delta = MOVE_DELTAS[direction]
        state.position = (state.position[0] + delta[0], state.position[1] + delta[1])
        if state.position == target:
            break

    assert state.position == target


def test_miner_targets_lowest_full_hub_stock() -> None:
    info = PolicyEnvInterface.from_mg_cfg(
        make_machina1_mission(num_agents=8).make_env()
    )
    policy = StarterCogPolicyImpl(info, agent_id=0, role="miner")
    features = {feature.name: feature for feature in info.obs_features}
    center = (info.obs_height // 2) * 16 + info.obs_width // 2
    values = [
        (center, "tag", info.tags.index("type:agent")),
        (center, "tag", info.tags.index("team:cogs")),
        (center, "inv:miner", 1),
        (center - 1, "tag", info.tags.index("type:carbon_extractor")),
        (center + 1, "tag", info.tags.index("type:oxygen_extractor")),
        (254, "team:carbon", 1),
        (254, "team:carbon:p1", 1),
        (254, "team:oxygen", 2),
        (254, "team:germanium", 3),
        (254, "team:silicon", 4),
    ]
    observation = AgentObservation(
        agent_id=0,
        tokens=[
            ObservationToken(
                feature=features[name],
                value=value,
                raw_token=(location, features[name].id, value),
            )
            for location, name, value in values
        ],
    )

    action, _ = policy.step_with_state(observation, policy.initial_agent_state())

    assert action.name == "move_east"


@pytest.mark.parametrize("stock,expected_action", [(7, "move_west"), (0, "move_east")])
def test_aligner_refills_only_when_hub_can_craft(
    stock: int, expected_action: str
) -> None:
    info = PolicyEnvInterface.from_mg_cfg(
        make_machina1_mission(num_agents=8).make_env()
    )
    policy = StarterCogPolicyImpl(info, agent_id=0, role="aligner")
    features = {feature.name: feature for feature in info.obs_features}
    center = (info.obs_height // 2) * 16 + info.obs_width // 2
    values = [
        (center, "tag", info.tags.index("type:agent")),
        (center, "tag", info.tags.index("team:cogs")),
        (center, "inv:aligner", 1),
        (center, "inv:heart", 2),
        (center, "inv:hp", 100),
        (center - 1, "tag", info.tags.index("type:hub")),
        (center - 1, "tag", info.tags.index("team:cogs")),
        (center + 1, "tag", info.tags.index("type:junction")),
        *(
            (254, f"team:{element}", stock)
            for element in ("carbon", "oxygen", "germanium", "silicon")
        ),
    ]
    observation = AgentObservation(
        agent_id=0,
        tokens=[
            ObservationToken(
                feature=features[name],
                value=value,
                raw_token=(location, features[name].id, value),
            )
            for location, name, value in values
        ],
    )

    action, _ = policy.step_with_state(observation, policy.initial_agent_state())

    assert action.name == expected_action


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


@pytest.mark.parametrize("remembered", [False, True])
def test_aligner_with_heart_gets_gear_before_frontier(remembered: bool) -> None:
    info = PolicyEnvInterface.from_mg_cfg(
        make_machina1_mission(num_agents=8).make_env()
    )
    policy = StarterCogPolicyImpl(info, agent_id=0, role="aligner")
    features = {feature.name: feature for feature in info.obs_features}
    center = (info.obs_height // 2) * 16 + info.obs_width // 2
    values = [
        (center, "tag", info.tags.index("type:agent")),
        (center, "tag", info.tags.index("team:cogs")),
        (center, "inv:heart", 1),
        (center, "inv:hp", 100),
        (center - 16, "tag", info.tags.index("type:hub")),
        (center - 16, "tag", info.tags.index("team:cogs")),
    ]
    state = policy.initial_agent_state()
    station_tags = {info.tags.index("type:aligner"), info.tags.index("team:cogs")}
    if remembered:
        state.seen_tags_by_position[(0, -8)] = station_tags
    else:
        values.extend((center - 1, "tag", tag) for tag in sorted(station_tags))
    observation = AgentObservation(
        agent_id=0,
        tokens=[
            ObservationToken(
                feature=features[name],
                value=value,
                raw_token=(location, features[name].id, value),
            )
            for location, name, value in values
        ],
    )

    action, _ = policy.step_with_state(observation, state)

    assert action.name == "move_west"
