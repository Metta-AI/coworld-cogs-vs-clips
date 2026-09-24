# Coworld Cogs vs Clips

Cogs vs Clips Coworld source package.

Cogs vs Clips is a team-based territory control game. Cog agents capture and hold junctions while Clips — automated opponents — continuously expand by seizing adjacent territory.

This repo owns the shared Cogs vs Clips Coworld game runtime, reference player, manifest, variants, and Docker build inputs for both the Cogs vs Clips and Four Score leagues.
The Python package remains `cogsguard`.

If docs, commands, runtime behavior, logs, or replays disagree while you are
building or submitting a Cogs vs Clips policy, preserve the evidence and file a
GitHub issue at <https://github.com/Metta-AI/coworld-cogs-vs-clips/issues>. For
Softmax play prompt or Coworld CLI issues, file against
<https://github.com/Metta-AI/coworld/issues>. Include the command, league/Coworld
ids, logs or replay links, and the smallest repro instead of silently working
around the issue.

## Install

```bash
pip install cogsguard
```

## Usage

```python
import cogsguard.game.game  # registers the "cogsguard" game
from cogsguard.core import get_game

game = get_game("cogsguard")
```

The game also provides a scripted MettaGrid teacher at
`cogsguard.policy.starter.StarterPolicy`. It assigns miner and aligner roles
by seat. `MinerRolePolicy`, `ScoutRolePolicy`, `AlignerRolePolicy`, and
`ScramblerRolePolicy` in the same module fix one role for all assigned seats.
Pass their full class paths in a MettaGrid `PolicySpec`. These policies use
player-visible observations and keep independent state per agent. They do not
switch roles during a game or establish a trained-policy quality baseline.

## Development

```bash
pip install -e '.[test]'
pytest
```

## Coworld Build

```bash
coworld build --version 0.2.38
coworld certify dist/coworld_manifest.json
coworld upload-coworld dist/coworld_manifest.json
```

## Typed semantic player

Build the optional Jev-style player with
`docker build -f Dockerfile.systemone-player -t cvc-systemone .`. It decodes
the seat-visible numeric observation with the game-owned semantic adapter,
offers the configured action names as typed candidates, and sends one action
for every simulator step. Model requests run in the background; the player
holds its last validated choice while a request is in flight.

The hosted player uses `AWS_ENDPOINT_URL_BEDROCK_RUNTIME` and the platform's
`/v1/systemone` sidecar route. For local TypeSafe trials, set
`COGAME_SYSTEMONE_URL=https://api.typesafe.ai/v1/systemone`,
`COGAME_SYSTEMONE_KEY`, and `COGAME_SYSTEMONE_MODEL=jev-latest`. Set
`COGAME_SYSTEMONE_INTERVAL_STEPS` to control request spacing (default 24).
Set `COGAME_DECISION_TRACE` to a new private path to journal each request,
raw typed answer, semantic observation, and submitted action with mode `0600`.
No provider key is written to that journal.

After a completed match, join one seat's journal to the game replay and
results with `python tools/export_semantic_trajectory.py --journal JOURNAL
--replay REPLAY --results RESULTS --output COMPLETE --episode-id ID
--source-revision COMMIT --policy-revision MODEL --seat SLOT` (on one line).
The exporter retains both submitted and simulator-applied actions. A mismatch
is retained as a fallback with no training label. Its `CompleteEpisode` output
is private (`0600`) and can be imported with Metta's `export-hosted` command.

## Local training bridge

`coworld/game/training_bridge.py` runs the same seeded mission simulator and
seat-visible observation as the hosted game. It serves the Metta JSONL decision
protocol for Metta RL, native PufferLib, and Metta post-training. Its numeric
codec contains the acting seat, remaining horizon, and all 500 observation
triples (1,502 values); its five choices match the player action names. The
text decision uses the existing Cogsguard semantic decoder to keep prompts
within the post-training token limit. The reference player supplies `noop`
teacher decisions. Numeric training does not model the player talk channel;
the semantic view retains visible talk, and verified hosted trajectories
capture submitted speech.

From a checkout with `cogsguard[coworld]` installed, run
`python coworld/game/training_bridge.py --variant machina-1-daily --steps 32`
as a JSONL subprocess. Other variants are `certification` and
`four-score-daily`. Omit `--steps` for the full published 10,000-step horizon.
The bridge accepts `reset`, `encode`, `teacher`, and `step` commands. `reset`
must name 8 players for CogsGuard/Machina 1 or 32 for Four Score.
Set Metta's `max_decisions` to at least `players * max_steps`; the published
10,000-step horizons need 80,000 or 320,000 interactions, respectively.
