"""Four Score mission: machina1 gameplay + 4-team corner compounds."""

from __future__ import annotations

from pydantic import Field

from cogsguard.game.teams.four_score import FourScoreVariant
from cogsguard.game.teams.identity_rotation import TeamIdentityRotation
from cogsguard.missions.machina_1 import make_machina1_map_builder
from cogsguard.missions.mission import CvCMission
from mettagrid.mapgen.mapgen import MapGenConfig
from mettagrid.simulator.interface import SimulatorEventHandler


class FourScoreMission(CvCMission):
    """Four Score: machina1 gameplay + 4-team corner compounds, no clips."""

    name: str = "four_score"
    description: str = "Multi-team corner bases competing for junction control."
    map_builder: MapGenConfig = Field(default_factory=lambda: make_machina1_map_builder(32))
    num_cogs: int = 32
    min_cogs: int = 4
    max_cogs: int = 80
    max_steps: int = 10000
    default_variant: str = "machina_1"
    num_agents: int = 32

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._base_variants["four_score"] = FourScoreVariant()


def four_score_event_handlers(seed: int | None = None) -> list[SimulatorEventHandler]:
    """Simulator handlers every Four Score episode runs alongside its config.

    The env config fixes the map and rules; team and agent identities in the
    observations are relabelled per episode by ``TeamIdentityRotation``, which
    the runner attaches to its ``Simulator``. ``seed`` makes the relabelling
    reproducible (it is mixed with each simulation's seed).
    """
    return [TeamIdentityRotation(seed=seed)]
