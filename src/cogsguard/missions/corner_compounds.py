"""Corner-compound layout: per-corner geometry, mirrored bases and team placement.

mettagrid's ``BiomeArena`` places corner compounds through ``FourCornerCompounds``,
which renders every corner from the FIRST corner's ``CompoundConfig`` (only the
hub, stations and spawn symbol vary per corner) inside floor-divided quadrants.
That cannot express three things multi-team missions want:

* mirrored bases: each corner's hub-adjacent cross arms and station row are a
  reflection of the north-east base, so "walk north to my junction" is not the
  same motor program in every base;
* equidistant bases: on an even map the floor division leaves the south/east
  hubs one tile nearer the centre than the north/west ones;
* team placement: a fresh team -> corner assignment drawn from the map RNG
  every time the map is built (i.e. every episode).

``CornerCompoundArena`` / ``CornerCompoundSequentialArena`` are the two mettagrid
arenas with their corner compounds placed by ``CornerCompounds`` instead of
``FourCornerCompounds``. Every other child of the arena (terrain, buildings,
connectivity, reachability) is unchanged, and with every option off the
generated map is identical to the stock arena's.
"""

from __future__ import annotations

from typing import Literal
from typing_extensions import override

from pydantic import Field, model_validator

from mettagrid.base_config import Config
from mettagrid.map_builder.map_builder import MapBuilderConfig
from mettagrid.mapgen.area import AreaWhere
from mettagrid.mapgen.mapgen import MapGen
from mettagrid.mapgen.scene import ChildrenAction, Scene, SceneConfig
from mettagrid.mapgen.scenes.biome_arena import (
    BiomeArena,
    BiomeArenaConfig,
    SequentialBiomeArena,
    SequentialBiomeArenaConfig,
)
from mettagrid.mapgen.scenes.compound import DEFAULT_EXTRACTORS, CompoundConfig
from mettagrid.mapgen.scenes.four_corner_compounds import FourCornerCompoundsConfig

CornerLocation = Literal["nw", "ne", "sw", "se"]
CORNER_ORDER: tuple[CornerLocation, ...] = ("nw", "ne", "sw", "se")

# The fields that make a compound one team's base. Team placement moves these
# between corners; everything else (the corner's geometry) stays put.
TEAM_IDENTITY_FIELDS: tuple[str, ...] = ("hub_object", "spawn_symbol", "stations")

# (mirror_x, mirror_y) that turns the north-east reference base into each corner.
_CORNER_MIRRORS: dict[CornerLocation, tuple[bool, bool]] = {
    "ne": (False, False),
    "nw": (True, False),
    "se": (False, True),
    "sw": (True, True),
}

# Distance of Compound's default station row below the hub (``_render_default_layout``).
_DEFAULT_STATION_ROW_DY = 4


def _default_station_offsets(compound: CompoundConfig) -> list[tuple[int, int]]:
    """Hub-relative offsets of Compound's default station row for ``compound``.

    Mirrors ``Compound._place_stations``: a row centred on the hub, spacing 2
    (compressed when the hub interior is too narrow), ``_DEFAULT_STATION_ROW_DY``
    below the hub.
    """
    n = len(compound.stations)
    if n == 0:
        return []
    interior_width = max(1, max(7, compound.hub_width) - 2)
    spacing = 1 if n <= 1 else min(2, max(1, (interior_width - 1) // (n - 1)))
    row_span = 1 + (n - 1) * spacing
    start_dx = -(row_span // 2)
    return [(start_dx + i * spacing, _DEFAULT_STATION_ROW_DY) for i in range(n)]


def mirror_compound(compound: CompoundConfig, loc: CornerLocation) -> CompoundConfig:
    """Return ``compound`` reflected from the north-east reference into ``loc``.

    The cross arms (N, E, S, W) swap across the mirror axes, and the station row
    is reflected with each offset still bound to its station, so an x-mirror
    reverses the row's type order exactly as a mirror image would. The four
    inner-corner objects, gates and spawn pads are already symmetric and keep
    their stock positions.
    """
    mirror_x, mirror_y = _CORNER_MIRRORS[loc]
    if not (mirror_x or mirror_y):
        return compound.model_copy(deep=True)

    update: dict = {}
    cross = compound.cross_objects
    if cross is None and compound.cross_bundle == "extractors":
        cross = list(DEFAULT_EXTRACTORS)
    if cross is not None and len(cross) == 4:
        north, east, south, west = cross
        if mirror_x:
            east, west = west, east
        if mirror_y:
            north, south = south, north
        update["cross_objects"] = [north, east, south, west]

    offsets = compound.station_offsets
    if offsets is None and compound.layout == "default":
        offsets = _default_station_offsets(compound)
    if offsets:
        update["station_offsets"] = [(-dx if mirror_x else dx, -dy if mirror_y else dy) for dx, dy in offsets]
    return compound.model_copy(deep=True, update=update)


def _hub_centre_offset(area_size: int, hub_size: int) -> int:
    """Offset of a compound's hub centre from the origin of the area it fills (see ``Compound.render``)."""
    hub = max(7, min(hub_size, area_size))
    return (area_size - hub) // 2 + hub // 2


class CornerCompoundsConfig(SceneConfig):
    """Place one compound per corner with per-corner geometry and team placement."""

    compounds: list[tuple[CornerLocation, CompoundConfig]] = Field(default_factory=list)
    spawn_count: int = 8
    mirror_interiors: bool = Field(
        default=False,
        description="Reflect each corner's cross arms and station row from the north-east base.",
    )
    equidistant: bool = Field(
        default=False,
        description="Place the corner areas so every hub is the same distance from the map centre.",
    )
    shuffle_teams: bool = Field(
        default=False,
        description="Draw a fresh team -> corner assignment from the map RNG every time the map is built.",
    )

    @model_validator(mode="after")
    def _validate(self) -> CornerCompoundsConfig:
        locs = [loc for loc, _ in self.compounds]
        if len(set(locs)) != len(locs):
            raise ValueError(f"corner locations must be unique, got {locs}")
        return self


class CornerCompounds(Scene[CornerCompoundsConfig]):
    """Render up to four compounds, one per named corner."""

    @override
    def render(self) -> None:
        for loc, (x, y, w, h) in self._corner_areas().items():
            self.make_area(x, y, w, h, tags=[f"corner_{loc}"])

    def _corner_areas(self) -> dict[CornerLocation, tuple[int, int, int, int]]:
        width, height = self.width, self.height
        half_w, half_h = width // 2, height // 2
        areas: dict[CornerLocation, tuple[int, int, int, int]] = {}
        for loc, compound in self.config.compounds:
            east, south = loc.endswith("e"), loc.startswith("s")
            if not self.config.equidistant:
                x, w = (half_w, width - half_w) if east else (0, half_w)
                y, h = (half_h, height - half_h) if south else (0, half_h)
            else:
                # Every corner uses the south-east quadrant's size. The south/east
                # corners keep their stock origin; the north/west ones are placed
                # so their hub centre is the reflection of that origin's hub
                # centre through the map centre.
                w, h = width - half_w, height - half_h
                x = half_w if east else width - 1 - half_w - 2 * _hub_centre_offset(w, compound.hub_width)
                y = half_h if south else height - 1 - half_h - 2 * _hub_centre_offset(h, compound.hub_height)
                if x < 0 or y < 0:
                    raise ValueError(f"map {width}x{height} is too small for equidistant corner compounds")
            areas[loc] = (x, y, w, h)
        return areas

    @override
    def get_children(self) -> list[ChildrenAction]:
        cfg = self.config
        locs = [loc for loc, _ in cfg.compounds]
        compounds = [c.model_copy(deep=True, update={"spawn_count": cfg.spawn_count}) for _, c in cfg.compounds]

        if cfg.shuffle_teams and len(compounds) > 1:
            order = [int(i) for i in self.rng.permutation(len(compounds))]
            identities = [{f: getattr(c, f) for f in TEAM_IDENTITY_FIELDS} for c in compounds]
            compounds = [c.model_copy(deep=True, update=identities[i]) for c, i in zip(compounds, order, strict=True)]

        if cfg.mirror_interiors:
            compounds = [mirror_compound(c, loc) for c, loc in zip(compounds, locs, strict=True)]

        return [
            ChildrenAction(scene=c, where=AreaWhere(tags=[f"corner_{loc}"]), limit=1, order_by="first")
            for loc, c in zip(locs, compounds, strict=True)
        ]


class CornerCompoundOptions(Config):
    """Corner options carried by both corner-compound arena configs."""

    mirror_corner_interiors: bool = False
    equidistant_corners: bool = False
    shuffle_team_corners: bool = False


class CornerCompoundArenaConfig(BiomeArenaConfig, CornerCompoundOptions):
    """A ``BiomeArenaConfig`` whose corner compounds are placed by ``CornerCompounds``."""

    # Unbind the inherited BiomeArena binding so CornerCompoundArena can bind
    # this config (same idiom as mettagrid's SequentialBiomeArenaConfig).
    _scene_cls = None


class CornerCompoundSequentialArenaConfig(SequentialBiomeArenaConfig, CornerCompoundOptions):
    """A ``SequentialBiomeArenaConfig`` whose corner compounds are placed by ``CornerCompounds``."""

    _scene_cls = None


class _CornerCompoundChildren:
    """Replaces the arena's ``FourCornerCompounds`` child with ``CornerCompounds``.

    Both mettagrid arenas emit their corner compounds as a single
    ``FourCornerCompoundsConfig`` child between the building and connectivity
    passes; swapping that one child keeps every other child, and its order, intact.
    """

    config: CornerCompoundOptions

    def get_children(self) -> list[ChildrenAction]:
        children = super().get_children()  # type: ignore[misc]
        for i, action in enumerate(children):
            if isinstance(action.scene, FourCornerCompoundsConfig):
                children[i] = action.model_copy(update={"scene": self._corner_compounds(action.scene)})
        return children

    def _corner_compounds(self, stock: FourCornerCompoundsConfig) -> CornerCompoundsConfig:
        cfg = self.config
        assert isinstance(cfg, BiomeArenaConfig)
        return CornerCompoundsConfig(
            compounds=[(loc, c.model_copy(deep=True)) for loc, c in cfg.compounds if loc != "center"],
            spawn_count=stock.spawn_count,
            mirror_interiors=cfg.mirror_corner_interiors,
            equidistant=cfg.equidistant_corners,
            shuffle_teams=cfg.shuffle_team_corners,
        )


class CornerCompoundArena(_CornerCompoundChildren, BiomeArena, Scene[CornerCompoundArenaConfig]):
    pass


class CornerCompoundSequentialArena(
    _CornerCompoundChildren, SequentialBiomeArena, Scene[CornerCompoundSequentialArenaConfig]
):
    pass


def use_corner_compound_arena(
    map_builder: MapBuilderConfig,
    *,
    mirror_interiors: bool = False,
    equidistant: bool = False,
    shuffle_teams: bool = False,
) -> CornerCompoundOptions | None:
    """Swap the biome arena inside ``map_builder`` for its corner-compound counterpart.

    ``SequentialBiomeArenaConfig`` becomes ``CornerCompoundSequentialArenaConfig``
    and ``BiomeArenaConfig`` becomes ``CornerCompoundArenaConfig``. The arena keeps
    every field it had; only the corner options are set. Returns the new arena
    config, or None when ``map_builder`` holds no biome arena.
    """
    parent = map_builder
    if not isinstance(parent, MapGen.Config):
        return None
    if isinstance(parent.instance, MapGen.Config):
        parent = parent.instance
    arena = parent.instance
    if isinstance(arena, SequentialBiomeArenaConfig):
        new_cls: type[BiomeArenaConfig] = CornerCompoundSequentialArenaConfig
    elif isinstance(arena, BiomeArenaConfig):
        new_cls = CornerCompoundArenaConfig
    else:
        return None
    fields = {name: getattr(arena, name) for name in BiomeArenaConfig.model_fields}
    fields.update(
        mirror_corner_interiors=mirror_interiors,
        equidistant_corners=equidistant,
        shuffle_team_corners=shuffle_teams,
    )
    new_arena = new_cls(**fields)
    parent.instance = new_arena
    assert isinstance(new_arena, CornerCompoundOptions)
    return new_arena
