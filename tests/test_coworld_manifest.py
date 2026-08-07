from __future__ import annotations

import json
from pathlib import Path

from coworld.certifier import build_manifest_episode_job_spec, load_coworld_package
from coworld.manifest_validation import game_config_with_tokens, validate_authored_game_config


def test_compose_builds_both_local_commissioners_for_upload() -> None:
    compose_text = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text(
        encoding="utf-8"
    )

    assert "coworld-cogs-vs-clips-commissioner:latest" in compose_text
    assert "RULESET_STRATEGY_CONFIG_NAME: cogs_vs_clips" in compose_text
    assert "coworld-four-score-commissioner:latest" in compose_text
    assert "RULESET_STRATEGY_CONFIG_NAME: four_score" in compose_text
    assert "ghcr.io/metta-ai/commissioners-cogs-vs-clips" not in compose_text


def test_shared_coworld_manifest_validates_both_league_variants(tmp_path: Path) -> None:
    template_path = (
        Path(__file__).resolve().parents[1] / "coworld_manifest_template.json"
    )
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest = json.loads(template_path.read_text(encoding="utf-8"))
    manifest["game"]["version"] = "0.2.18"
    manifest["game"]["runnable"]["image"] = "coworld-cogs-vs-clips-game:latest"
    manifest["player"][0]["image"] = "coworld-cogs-vs-clips-reference-player:latest"
    manifest["commissioner"][0]["image"] = "coworld-cogs-vs-clips-commissioner:latest"
    manifest["commissioner"][1]["image"] = "coworld-four-score-commissioner:latest"
    assert manifest["tags"] == ["multi-agent", "resource-management", "strategy"]
    assert manifest["game"]["replay_viewer"] == {"bundle": "static-replay-viewer"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert (
        manifest["game"]["runnable"]["source_url"]
        == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main"
    )

    package = load_coworld_package(manifest_path)
    tokens = [f"token-{index}" for index in range(8)]
    config = game_config_with_tokens(build_manifest_episode_job_spec(package).game_config, tokens)
    pages = {page.id: page.content.value for page in package.manifest.game.docs.pages}

    assert package.manifest.game.name == "cogs_vs_clips"
    assert package.manifest.game.replay_viewer is not None
    assert package.manifest.game.replay_viewer.bundle == "static-replay-viewer"
    assert package.manifest.game.docs.readme is not None
    assert (
        package.manifest.game.docs.readme.value
        == "https://github.com/Metta-AI/coworld-cogs-vs-clips/blob/main/README.md"
    )
    assert package.manifest.game.protocols.player.value == (
        "https://github.com/Metta-AI/coworld-cogs-vs-clips/blob/main/coworld/game/docs/player_protocol_spec.md"
    )
    assert package.manifest.game.protocols.global_.value == (
        "https://github.com/Metta-AI/coworld-cogs-vs-clips/blob/main/coworld/game/docs/global_protocol_spec.md"
    )
    assert pages["rules.md"] == "https://softmax.com/play_cogsvsclips.md#game-rules"
    assert pages["play_cogsvsclips.md"] == "https://softmax.com/play_cogsvsclips.md"
    assert (
        pages["game-source"]
        == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main"
    )
    assert (
        pages["player"]
        == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main/coworld/player"
    )
    assert package.game.image == "coworld-cogs-vs-clips-game:latest"
    assert package.game.run == ("python", "/app/server.py")
    assert package.manifest.player[0].id == "reference-player"
    assert (
        package.manifest.player[0].image
        == "coworld-cogs-vs-clips-reference-player:latest"
    )
    assert package.manifest.player[0].run == [
        "python",
        "/app/coworld_reference_player.py",
    ]
    assert (
        package.manifest.player[0].source_url
        == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main/coworld/player"
    )
    assert package.manifest.reporter == []
    assert package.manifest.grader == []
    cogs_vs_clips_variant = next(
        variant
        for variant in package.manifest.variants
        if variant.id == "machina-1-daily"
    )
    four_score_variant = next(
        variant
        for variant in package.manifest.variants
        if variant.id == "four-score-daily"
    )
    assert cogs_vs_clips_variant.game_config["max_steps"] == 10000
    assert four_score_variant.game_config["mission"] == "four_score"
    assert len(four_score_variant.game_config["players"]) == 32
    validate_authored_game_config(
        cogs_vs_clips_variant.game_config,
        package.manifest.game.config_schema,
    )
    validate_authored_game_config(
        four_score_variant.game_config,
        package.manifest.game.config_schema,
    )
    assert [role.id for role in package.manifest.commissioner] == [
        "cogs-vs-clips-commissioner",
        "four-score-commissioner",
    ]
    assert config == {
        "players": [
            {"name": "Player 1"},
            {"name": "Player 2"},
            {"name": "Player 3"},
            {"name": "Player 4"},
            {"name": "Player 5"},
            {"name": "Player 6"},
            {"name": "Player 7"},
            {"name": "Player 8"},
        ],
        "mission": "cogsguard",
        "max_steps": 3,
        "seed": 0,
        "step_seconds": 0.02,
        "tokens": tokens,
    }
