# Coworld Cogs vs Clips

<!-- COWORLD-VERIFY-BADGE:START -->
![Coworld verify: not ready](https://img.shields.io/badge/coworld%20verify-not%20ready-lightgrey)
<!-- COWORLD-VERIFY-BADGE:END -->


<!-- COWORLD-REPO-STATUS:START -->
> [!NOTE]
> Coworld repo status: **template** (`coworld-template`).
> Canonical repository: `Metta-AI/coworld-cogs-vs-clips`.
> Manifest path: `coworld_manifest_template.json`.
> Build path: `Dockerfile.game`, `Dockerfile.player`
> Certification: blocked until this template resolves to a concrete `coworld_manifest.json` and `uv run coworld certify coworld_manifest.json` passes.
>
> Missing pieces:
> - [ ] Resolve `coworld_manifest_template.json` into a concrete root `coworld_manifest.json`.
> - [ ] Confirm buildable game and starter-player images.
> - [ ] Run `uv run coworld certify coworld_manifest.json` and record the passing command.
<!-- COWORLD-REPO-STATUS:END -->


Cogs vs Clips Coworld source package.

Cogs vs Clips is a team-based territory control game. Cog agents capture and hold junctions while Clips — automated opponents — continuously expand by seizing adjacent territory.

This repo owns the Cogs vs Clips and Four Score Coworld game runtime, reference player, reporter declarations, manifest templates, and Docker build inputs.
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

## Development

```bash
pip install -e '.[test]'
pytest
```

## Coworld Build

```bash
coworld build compose.yaml coworld_manifest_template.json 0.2.18 tmp/coworld_manifest.json
coworld certify tmp/coworld_manifest.json
coworld resolve-and-upload compose.yaml coworld_manifest_template.json 0.2.18 tmp/coworld_manifest.json

coworld build compose.yaml coworld_four_score_manifest_template.json 0.1.0 tmp/four_score_manifest.json
```
