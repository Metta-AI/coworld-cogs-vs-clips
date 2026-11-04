"""Four Score map layout: mirrored, equidistant bases and a per-episode team -> corner draw."""

from __future__ import annotations

import numpy as np
import pytest

from cogsguard.game.teams.four_score import RESERVED_TAG, TEAM_COLORS
from cogsguard.missions.corner_compounds import (
    CornerCompoundSequentialArenaConfig,
    use_corner_compound_arena,
)
from cogsguard.missions.four_score import FourScoreMission, four_score_event_handlers
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.mapgen.scenes.biome_arena import BiomeArenaConfig, SequentialBiomeArenaConfig
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Simulator

SHORT_COLORS = [color[:3] for color in TEAM_COLORS]
# Station types left to right in the north-east (reference) base.
REFERENCE_STATION_TYPES = ["aligner", "scrambler", "miner", "scout"]
SPAWN_CROSS = {(0, -3), (0, -2), (0, 2), (0, 3), (-3, 0), (-2, 0), (2, 0), (3, 0)}


def _build_grid(env: MettaGridConfig, seed: int) -> np.ndarray:
    env.game.map_builder.seed = seed
    return env.game.map_builder.create().build().grid.astype(str)


def _four_score_grid(seed: int) -> np.ndarray:
    return _build_grid(FourScoreMission().make_env(), seed)


def _bases(grid: np.ndarray) -> dict[str, dict]:
    """Per corner: hub position and colour, plus the junction, stations and spawn pads around the hub."""
    height, width = grid.shape
    is_station = np.vectorize(lambda name: ":" in name and not name.endswith(":hub"))
    bases = {}
    for y, x in zip(*np.where(np.char.endswith(grid, ":hub")), strict=True):
        corner = ("n" if y < height / 2 else "s") + ("w" if x < width / 2 else "e")
        window = grid[y - 10 : y + 11, x - 10 : x + 11]

        def cells(mask: np.ndarray) -> list[tuple[int, int, str]]:
            return sorted((int(c) - 10, int(r) - 10, str(window[r, c])) for r, c in zip(*np.where(mask), strict=True))

        bases[corner] = {
            "hub": (int(x), int(y)),
            "colour": str(grid[y, x]).split(":")[0],
            "junction": [(dx, dy) for dx, dy, _ in cells(window == "junction")],
            "stations": cells(is_station(window)),
            "spawns": cells(np.char.startswith(window, "agent.")),
        }
    return bases


def test_four_score_places_corners_with_the_corner_compound_arena() -> None:
    arena = FourScoreMission().make_env().game.map_builder.instance
    assert isinstance(arena, CornerCompoundSequentialArenaConfig)
    assert arena.mirror_corner_interiors
    assert arena.equidistant_corners
    assert arena.shuffle_team_corners


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_corner_compound_arena_with_every_option_off_builds_the_stock_map(seed: int) -> None:
    env = FourScoreMission().make_env()
    stock_env = env.model_copy(deep=True)
    arena = env.game.map_builder.instance
    stock_env.game.map_builder.instance = SequentialBiomeArenaConfig(
        **{name: getattr(arena, name) for name in BiomeArenaConfig.model_fields}
    )
    use_corner_compound_arena(env.game.map_builder)

    assert np.array_equal(_build_grid(env, seed), _build_grid(stock_env, seed))


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_bases_are_mirror_images_of_the_north_east_base(seed: int) -> None:
    bases = _bases(_four_score_grid(seed))
    assert sorted(bases) == ["ne", "nw", "se", "sw"]
    for corner, base in bases.items():
        south, west = corner.startswith("s"), corner.endswith("w")
        assert base["junction"] == [(0, 4 if south else -4)]
        row_dy = -4 if south else 4
        assert [(dx, dy) for dx, dy, _ in base["stations"]] == [(dx, row_dy) for dx in (-3, -1, 1, 3)]
        types = [name.split(":")[1] for *_, name in base["stations"]]
        assert types == (REFERENCE_STATION_TYPES[::-1] if west else REFERENCE_STATION_TYPES)
        assert {(dx, dy) for dx, dy, _ in base["spawns"]} == SPAWN_CROSS


def test_hubs_are_equidistant_from_the_map_centre() -> None:
    grid = _four_score_grid(1)
    height, width = grid.shape
    centre_x, centre_y = (width - 1) / 2, (height - 1) / 2
    hubs = [base["hub"] for base in _bases(grid).values()]
    assert len(hubs) == 4
    assert len({(abs(x - centre_x), abs(y - centre_y)) for x, y in hubs}) == 1


def test_team_identity_moves_between_corners_as_a_unit() -> None:
    team_corners: set[tuple[str, str]] = set()
    for seed in range(1, 33):
        bases = _bases(_four_score_grid(seed))
        assert sorted(base["colour"] for base in bases.values()) == sorted(SHORT_COLORS)
        for corner, base in bases.items():
            team = SHORT_COLORS.index(base["colour"])
            assert {name.split(":")[0] for *_, name in base["stations"]} == {base["colour"]}
            assert {name for *_, name in base["spawns"]} == {f"agent.team_{team}"}
            team_corners.add((base["colour"], corner))
    assert len(team_corners) == 16, "every team should start in every corner over 32 maps"


def test_team_corners_are_reproducible_from_the_map_seed() -> None:
    def assignment(seed: int) -> dict[str, str]:
        return {corner: base["colour"] for corner, base in _bases(_four_score_grid(seed)).items()}

    assert assignment(5) == assignment(5)


def test_every_episode_redraws_the_corners_and_agents_start_at_their_own_hub() -> None:
    env = FourScoreMission().make_env()
    env.game.map_builder.seed = 11
    tag_names = PolicyEnvInterface.from_mg_cfg(env).tag_id_to_name
    simulator = Simulator()
    assignments = set()
    for episode in range(6):
        sim = simulator.new_simulation(env, seed=episode)
        objects = list(sim.grid_objects().values())
        hubs = {
            tag_names[tag_id]: (o["r"], o["c"])
            for o in objects
            if o["type_name"] == "hub"
            for tag_id in o["tag_ids"]
            if tag_names[tag_id].startswith("team:")
        }
        assert len(hubs) == 4
        agents = [o for o in objects if o.get("agent_id") is not None]
        assert len(agents) == 32
        for agent in agents:
            hub_r, hub_c = hubs[f"team:cogs_{agent['group_name']}"]
            assert abs(agent["r"] - hub_r) <= 3 and abs(agent["c"] - hub_c) <= 3
        assignments.add(tuple(sorted(hubs.items(), key=lambda item: item[1])))
        sim.close()
    assert len(assignments) > 1


def test_tag_id_zero_is_reserved_so_no_observed_tag_is_zero() -> None:
    env = FourScoreMission().make_env()
    env.game.map_builder.seed = 2
    tag_names = PolicyEnvInterface.from_mg_cfg(env).tag_id_to_name
    assert tag_names[0] == RESERVED_TAG
    simulator = Simulator()
    for handler in four_score_event_handlers(seed=0):
        simulator.add_event_handler(handler)
    sim = simulator.new_simulation(env, seed=2)
    tag_feature = next(int(f.id) for f in sim.features if f.name == "tag")
    for _ in range(3):
        obs = sim._c_sim.observations()
        tags = obs[:, :, 2][(obs[:, :, 1] == tag_feature) & (obs[:, :, 0] != 0xFF)]
        assert tags.size and tags.min() >= 1
        assert RESERVED_TAG not in {tag_names[int(t)] for t in tags}
        for agent in range(sim.num_agents):
            sim.agent(agent).set_action("noop")
        sim.step()
    sim.close()
