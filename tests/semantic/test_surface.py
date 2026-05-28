from cogsguard.semantic import CogsguardEventExtractor, CogsguardSemanticSurface
from mettagrid.sdk.agent import GridPosition, MettagridState, SelfState, SemanticEntity, TeamSummary


def _state(
    *,
    step: int,
    inventory: dict[str, int] | None = None,
    visible_entities: list[SemanticEntity] | None = None,
) -> MettagridState:
    return MettagridState(
        game="cogsguard",
        step=step,
        self_state=SelfState(
            entity_id="agent-0",
            entity_type="agent",
            position=GridPosition(x=0, y=0),
            labels=["friendly", "team:red"],
            attributes={"team": "red"},
            inventory=inventory or {},
        ),
        visible_entities=visible_entities or [],
        team_summary=TeamSummary(team_id="red"),
    )


def test_semantic_surface_exports_game_adapter() -> None:
    surface = CogsguardSemanticSurface()

    assert isinstance(surface.event_extractor, CogsguardEventExtractor)


def test_event_extractor_marks_heart_acquisition() -> None:
    events = CogsguardEventExtractor().extract_events(
        _state(step=1),
        _state(step=2, inventory={"heart": 1}),
    )

    assert [event.event_type for event in events] == ["heart_acquired"]


def test_event_extractor_marks_new_enemy_visibility() -> None:
    events = CogsguardEventExtractor().extract_events(
        _state(step=1),
        _state(
            step=2,
            visible_entities=[
                SemanticEntity(
                    entity_id="agent-4",
                    entity_type="agent",
                    position=GridPosition(x=1, y=0),
                    labels=["enemy", "team:blue"],
                    attributes={"team": "blue", "role": "scrambler"},
                )
            ],
        ),
    )

    assert [event.event_type for event in events] == ["enemy_seen"]
