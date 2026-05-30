# coworld-cogs-vs-clips

Cogs vs Clips Coworld source package.

Cogs vs Clips is a team-based territory control game. Cog agents capture and hold junctions while Clips — automated opponents — continuously expand by seizing adjacent territory.

This repo owns the `cogs_vs_clips` Coworld game runtime, reference player, reporter declarations, manifest template, and Docker build inputs.
The Python package remains `cogsguard`.

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
```
