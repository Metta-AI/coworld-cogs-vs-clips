"""Four Corners variant: 1-4 teams in corner compounds.

The bases are mirror images of the north-east base (the hub junction and the
gear-station row point out of each corner rather than always north/south), every
hub is the same distance from the map centre, and the team -> corner assignment
is drawn afresh from the map RNG each episode. Corner geometry stays with the
corner, so over many episodes every team plays every base layout. See
``cogsguard.missions.corner_compounds``. Tag id 0 is reserved (``RESERVED_TAG``),
so no observed tag value is 0.
"""

from __future__ import annotations

from typing_extensions import override

from pydantic import Field

from cogsguard.core import CogsguardMissionVariant, Deps
from cogsguard.game.clips.clips import NoClipsVariant
from cogsguard.game.extractors import ExtractorsVariant
from cogsguard.game.teams.team import TeamConfig, TeamVariant
from cogsguard.missions.corner_compounds import use_corner_compound_arena
from cogsguard.missions.mission import CvCMission
from cogsguard.missions.terrain import CompoundLocation, MachinaTerrainVariant
from cogsguard.variants import ResolvedDeps
from mettagrid.config.game_value import SumGameValue, num_tagged, val, weighted_sum
from mettagrid.config.handler_config import Handler, allOf
from mettagrid.config.mettagrid_config import MettaGridConfig
from mettagrid.config.mutation import logStatToGame
from mettagrid.mapgen.scenes.compound import CompoundConfig

TEAM_COLORS = ["red", "blue", "green", "yellow"]
CORNER_LOCS: list[CompoundLocation] = ["nw", "ne", "sw", "se"]

# Tag ids are the positions of the env's tag names in sorted order, and an
# observation carries a tag as its id. Id 0 would therefore reach a policy as 0,
# the same value an empty cell has. Four Score gives id 0 to this tag, which sorts
# before every real tag and is never carried, so every observed tag is 1 or more.
RESERVED_TAG = "!reserved:tag_id_0"


class FourScoreVariant(CogsguardMissionVariant):
    """Set up 1-4 teams with corner compounds."""

    name: str = "four_score"
    description: str = "Multi-team corner compounds."
    num_teams: int = Field(default=4, ge=1, le=4)

    @override
    def dependencies(self) -> Deps:
        # Lazy import: cogsguard.missions.machina_1 → cogsguard.game.cargo →
        # cogsguard.game.__init__ → cogsguard.game.teams.four_score is a cycle.
        # Deferring keeps the type reference off the module-init path.
        from cogsguard.missions.machina_1 import CvCMachina1Variant  # noqa: PLC0415

        return Deps(
            required=[
                CvCMachina1Variant,
                TeamVariant,
                NoClipsVariant,
                MachinaTerrainVariant,
                ExtractorsVariant,
            ]
        )

    @override
    def configure(self, deps: ResolvedDeps) -> None:
        # Set up teams.
        team_v = deps.required(TeamVariant)
        team_v.teams = {
            f"cogs_{TEAM_COLORS[i]}": TeamConfig(
                name=f"cogs_{TEAM_COLORS[i]}",
                short_name=TEAM_COLORS[i][:3],
            )
            for i in range(self.num_teams)
        }

        # Reduce extractor stock for four-score so corners do not start too rich.
        deps.required(ExtractorsVariant).initial_amount = 100

        # Configure terrain with corner compounds.
        terrain = deps.required(MachinaTerrainVariant)
        terrain.map_width = 120
        terrain.map_height = 120
        terrain.building_coverage_scale = 1.5
        terrain.compound_placements = [
            (
                CORNER_LOCS[i],
                CompoundConfig(
                    hub_object=f"{TEAM_COLORS[i][:3]}:hub",
                    corner_bundle="extractors",
                    cross_objects=["junction", "", "", ""],
                    cross_distance=4,
                    outer_clearance=1,
                    spawn_symbol=f"agent.team_{i}",
                ),
            )
            for i in range(self.num_teams)
        ]

    @override
    def modify_env(self, mission: CvCMission, env: MettaGridConfig) -> None:
        # Runs after MachinaTerrainVariant has placed the compounds in the arena.
        arena = use_corner_compound_arena(
            env.game.map_builder,
            mirror_interiors=True,
            equidistant=True,
            shuffle_teams=True,
        )
        if arena is None:
            raise TypeError("four_score needs a MapGen map builder with a biome arena")
        if RESERVED_TAG not in env.game.tags:
            env.game.tags.append(RESERVED_TAG)

        team_v = mission.required_variant(TeamVariant)
        seen_team_names: set[str] = set()
        held_junction_stats: list[SumGameValue] = []

        # Machina-1 already installs the per-team held rewards and team stats.
        # Four Score only adds the aggregate cross-team stat used for progress.
        for agent in env.game.agents:
            team_name = team_v.team_name(agent.team_id)
            assert team_name is not None, f"agent team_id={agent.team_id} has no team name"
            if team_name in seen_team_names:
                continue
            held_junction_stats.append(SumGameValue(values=[num_tagged(f"net:{team_name}"), val(-1.0)]))
            seen_team_names.add(team_name)

        if held_junction_stats:
            avg_held_junctions = weighted_sum(
                [(1.0 / len(held_junction_stats), held_stat) for held_stat in held_junction_stats]
            )
            handler = Handler(
                name="aligned_junction_held_four_score_avg",
                mutations=[logStatToGame("four_score/aligned.junction.held.avg", source=avg_held_junctions)],
            )
            env.game.on_tick = allOf([env.game.on_tick, handler])
