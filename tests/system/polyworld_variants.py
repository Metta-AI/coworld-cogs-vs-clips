"""Protect shared-Coworld dispatch: each variant must run and replay its own game.

Build both upstream native/hosted modes, then run:
    python tests/system/polyworld_variants.py --binaries vendor/polyworld-cogs-vs-clips/out
Uses real hosted processes, the public Coworld episode planner, and full matches.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from coworld.certifier import build_manifest_episode_job_spec, load_coworld_package
from coworld.manifest_validation import game_config_with_tokens
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binaries", type=Path, required=True)
    args = parser.parse_args()
    binaries = args.binaries.resolve()
    evidence = Path(tempfile.mkdtemp(prefix="coworld-cogs-vs-clips-qa-variants-"))
    print("Evidence:", evidence, flush=True)
    template = json.loads((ROOT / "coworld_manifest_template.json").read_text())
    template["game"]["version"] = "0.3.0"
    shutil.copyfile(ROOT / template["player"][1]["file"], evidence / "baseline.bas")
    template["player"][1]["file"] = "baseline.bas"
    manifest_path = evidence / "manifest.json"
    manifest_path.write_text(json.dumps(template))
    package = load_coworld_package(manifest_path)
    policy = evidence / "idle.bas"
    policy.write_text("act(0)\n")
    games = {
        "{{POLYWORLD_COOPERATIVE_IMAGE}}": (
            "cvc-cooperative-hosted",
            "cvc-cooperative",
        ),
        "{{POLYWORLD_FOURSCORE_IMAGE}}": ("cvc-hosted", "cvc-headless"),
    }
    for variant in package.manifest.variants:
        if not variant.id.startswith("polyworld-"):
            continue
        count = len(variant.game_config["players"])
        job = build_manifest_episode_job_spec(
            package, variant_id=variant.id, player_files=[policy] * count
        )
        hosted, native = games[job.manifest.game.runnable.image]
        directory = evidence / variant.id
        directory.mkdir()
        config = game_config_with_tokens(
            job.game_config, [f"secret-{i}" for i in range(count)]
        )
        validate(config, package.config_schema)
        (directory / "config.json").write_text(json.dumps(config))
        roster = {
            "schema": "coworld-play-seats/2",
            "seats": [
                {
                    "slot": slot,
                    "kind": "policy",
                    "file_uri": policy.as_uri(),
                    "content_hash": "",
                    "size_bytes": policy.stat().st_size,
                    "log_uri": (directory / f"player-{slot}.log").as_uri(),
                    "artifact_uri": (directory / f"player-{slot}.zip").as_uri(),
                }
                for slot in range(count)
            ],
            "player_status_uri": (directory / "status.json").as_uri(),
        }
        (directory / "seats.json").write_text(json.dumps(roster))
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env = dict(os.environ, COGAME_PORT=str(port), COGAME_HOST="127.0.0.1")
        for key, filename in [
            ("CONFIG", "config.json"),
            ("PLAYER_SEATS", "seats.json"),
            ("RESULTS", "results.json"),
            ("SAVE_REPLAY", "episode.replay"),
            ("PLAYER_FAILURE", "failure.json"),
        ]:
            env[f"COGAME_{key}_URI"] = (directory / filename).as_uri()
        with (directory / "game.log").open("w") as log:
            process = subprocess.Popen(
                [binaries / hosted], env=env, stdout=log, stderr=log
            )
            try:
                deadline = time.monotonic() + 120
                result_path = directory / "results.json"
                while not result_path.exists():
                    assert process.poll() is None, (directory / "game.log").read_text()
                    assert not (directory / "failure.json").exists()
                    assert time.monotonic() < deadline, "Hosted episode timed out"
                    time.sleep(0.02)
                result = json.loads(result_path.read_text())
                validate(result, package.manifest.game.results_schema)
                assert result["ticks"] == 10000 and len(result["scores"]) == count
                replay = subprocess.check_output(
                    [binaries / native, "--replay", directory / "episode.replay"],
                    text=True,
                    timeout=120,
                )
                assert "tick=10000" in replay, replay
                for player in config["players"]:
                    assert (
                        player["name"].encode()
                        in (directory / "episode.replay").read_bytes()
                    )
                print("PASS", variant.id, replay.strip(), flush=True)
            finally:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
