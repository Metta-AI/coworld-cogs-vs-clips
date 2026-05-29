from __future__ import annotations

_COGSGUARD_SKILLS = (
    (
        "resource_coverage",
        "Mine missing elements, then deposit before overcarrying. "
        "resource_bias only prefers a resource type; it does not hard-lock one extractor.",
    ),
    (
        "focused_extractor_lock",
        "When one exact extractor is productive or oscillation is detected, "
        "set target_entity_id to pin that extractor until facts change.",
    ),
    (
        "teammate_shadowing",
        "If coordination requires staying together, set target_entity_id to a visible friendly agent like "
        "agent-1 to shadow them until the local situation changes.",
    ),
    (
        "region_reanchor",
        "Use target_region for west/east/frontier steering when you want lane pressure "
        "or exploration without pinning one entity yet.",
    ),
    (
        "heart_gated_alignment",
        "Aligners and scramblers should secure a heart before committing to junction pressure.",
    ),
    ("safe_deposit_cycle", "If carrying payload under pressure or low HP, route back toward a friendly hub."),
    ("lane_pressure", "Once hearts are online, convert spare pressure into aligner or scrambler lane control."),
)

_COGSGUARD_BEST_PRACTICES = (
    "Prefer one strong steering primitive at a time: target_entity_id first, then target_region, then resource_bias.",
    (
        'Use sdk.helpers.nearest_visible_entity(entity_type="junction", label="neutral") '
        "to choose one decisive focus target."
    ),
    (
        'Use sdk.helpers.visible_entities(entity_type="junction", label="enemy") '
        "to inspect lane pressure without pinning one id yet."
    ),
    (
        "Use sdk.helpers.shared_inventory() and sdk.helpers.recent_event_types() "
        "as progress signals before escalating phases or rewriting plans."
    ),
    (
        "Only use sdk.state fields and helpers that are explicitly documented; do not invent convenience flags such "
        "as sdk.state.just_deposited."
    ),
    (
        "If talk mode is enabled, the talk directive field is live: set talk to emit a short speech bubble over "
        "your cog, and nearby talking agents show up directly in visible_entities with label=talking plus "
        "talk_text/talk_remaining_steps attributes."
    ),
    (
        "If you must stay in observation range for coordination, set target_entity_id to a visible teammate "
        "entity_id such as agent-1 instead of hoping the baseline wanders nearby."
    ),
    (
        "Keep step(sdk) short and strategic; let the semantic baseline handle movement, mining, "
        "deposits, and junction actions."
    ),
    "If a target stops being productive, change directive fields or phase instead of layering more timeout ladders.",
)

_CONTROL_PRIMITIVES = (
    "role: choose miner, aligner, or scrambler to switch the semantic baseline behavior family",
    "objective: choose resource_coverage, economy_bootstrap, or aligner_pressure for the current phase",
    "target_entity_id: strongest focus primitive; use it for one exact extractor, junction, "
    "or visible entity such as a teammate agent-1 when you need to shadow them",
    "target_region: broader lane or region bias when you do not want to pin one exact entity yet",
    "resource_bias: resource-type preference among viable extractors; not a hard lock on one extractor",
    "talk: optional <=140-char coordination message; this is the canonical communication "
    "field when talk mode is enabled",
)


def render_cogsguard_skill_library() -> str:
    return "\n".join(
        [
            "SKILLS",
            *(f"- {name}: {description}" for name, description in _COGSGUARD_SKILLS),
            "CONTROL_PRIMITIVES",
            *(f"- {line}" for line in _CONTROL_PRIMITIVES),
            "BEST_PRACTICES",
            *(f"- {line}" for line in _COGSGUARD_BEST_PRACTICES),
        ]
    )
