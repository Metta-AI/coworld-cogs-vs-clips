from __future__ import annotations

import json
from pathlib import Path

from coworld.certifier import build_manifest_episode_job_spec, load_coworld_package
from coworld.manifest_validation import game_config_with_tokens


def test_cogs_vs_clips_compose_builds_local_commissioner_for_upload() -> None:
    compose_text = (Path(__file__).resolve().parents[1] / "compose.yaml").read_text(
        encoding="utf-8"
    )

    assert "coworld-cogs-vs-clips-commissioner:latest" in compose_text
    assert "RULESET_STRATEGY_CONFIG_NAME: cogs_vs_clips" in compose_text
    assert "ghcr.io/metta-ai/commissioners-cogs-vs-clips" not in compose_text


def test_cogs_vs_clips_coworld_manifest_validates(tmp_path: Path) -> None:
    template_path = (
        Path(__file__).resolve().parents[1] / "coworld_manifest_template.json"
    )
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest = json.loads(template_path.read_text(encoding="utf-8"))
    manifest["game"]["version"] = "0.2.18"
    manifest["game"]["runnable"]["image"] = "coworld-cogs-vs-clips-game:latest"
    manifest["player"][0]["image"] = "coworld-cogs-vs-clips-reference-player:latest"
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
    assert package.manifest.reporter[0].id == "softmax-default-reporter"
    assert (
        package.manifest.reporter[0].image
        == "coworld-cogs-vs-clips-default-reporter:latest"
    )
    assert (
        package.manifest.reporter[0].source_url
        == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main/reporter/default"
    )
    assert package.manifest.reporter[1].id == "cogs-vs-clips-summarizer"
    assert (
        package.manifest.reporter[1].image
        == "coworld-cogs-vs-clips-reporter:latest"
    )
    assert (
        package.manifest.reporter[1].source_url
        == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main/reporter/cogs_vs_clips/cogs_vs_clips_summarizer"
    )
    assert package.manifest.grader is not None
    assert len(package.manifest.grader) == 1
    assert (
        package.manifest.grader[0].source_url
        == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main/grader/graders/cogs_v_clips/cogs_v_clips_grader"
    )
    daily_variant = next(
        variant
        for variant in package.manifest.variants
        if variant.id == "machina-1-daily"
    )
    assert daily_variant.game_config["max_steps"] == 10000
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


def test_four_score_coworld_manifest_validates(tmp_path: Path) -> None:
    template_path = (
        Path(__file__).resolve().parents[1] / "four_score" / "coworld_manifest_template.json"
    )
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest = json.loads(template_path.read_text(encoding="utf-8"))
    manifest["game"]["version"] = "0.1.0"
    manifest["game"]["runnable"]["image"] = "coworld-four-score-game:latest"
    manifest["player"][0]["image"] = "coworld-four-score-reference-player:latest"
    manifest["commissioner"][0]["image"] = "coworld-four-score-commissioner:latest"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    package = load_coworld_package(manifest_path)
    tokens = [f"token-{index}" for index in range(32)]
    config = game_config_with_tokens(build_manifest_episode_job_spec(package).game_config, tokens)
    pages = {page.id: page.content.value for page in package.manifest.game.docs.pages}

    assert package.manifest.game.name == "four_score"
    assert package.manifest.game.runnable.source_url == (
        "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main"
    )
    assert (
        pages["game-source"]
        == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main"
    )
    assert (
        pages["player"]
        == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main/coworld/player"
    )
    assert package.manifest.player[0].source_url == (
        "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main/coworld/player"
    )
    assert [role.id for role in package.manifest.commissioner] == ["four-score-commissioner"]
    assert package.manifest.commissioner[0].source_url == (
        "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main/commissioner/commissioners/ruleset_strategy_commissioner"
    )
    assert [role.id for role in package.manifest.reporter] == [
        "softmax-default-reporter",
        "cogs-vs-clips-summarizer",
    ]
    daily_variant = package.manifest.variants[0]
    assert daily_variant.id == "four-score-daily"
    assert daily_variant.game_config["mission"] == "four_score"
    assert len(daily_variant.game_config["players"]) == 32
    assert config["mission"] == "four_score"
    assert config["max_steps"] == 3
    assert config["tokens"] == tokens
    assert len(config["players"]) == 32
