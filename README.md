# Coworld Cogs vs Clips

Cogs vs Clips Coworld source package.

Cogs vs Clips is a cooperative territory game: eight Cogs share a home and a
resource bank while automated Clips spread across the map. Each Cog runs an AI
policy. You build its decision-making; the team must turn local observations
into coordinated gathering, expansion, and defense.

Mine carbon, oxygen, germanium, and silicon to supply the shared bank. Equip
miners to gather, scouts to explore, aligners to capture junctions, and scramblers
to disrupt enemy territory. Hearts pay for captures and scrambling. Keep captured
junctions connected to your hub: a broken connection can cost the team its territory.

In the Polyworld modes, each 10,000-tick match scores the average number of
junctions a team holds. All teammates share that score. Cooperative Cogs vs Clips
uses eight independently submitted policies against automated Clips. **FourScore**
puts four teams of eight Cogs on the map, with no automated Clips and separate standings.

Start from the [participation guide](https://softmax.com/cogs-vs-clips/play.md),
then inspect the [Polyworld rules](https://github.com/softmax-universe/polyworld-cogs-vs-clips/blob/main/docs/rules.md)
and [cooperative mode](https://github.com/softmax-universe/polyworld-cogs-vs-clips/blob/main/docs/cooperative-migration.md).
BASIC programs and qualified Docker policies can share Polyworld matches.
Watch replays to see whether your Cog kept the team supplied, reached useful
junctions, or left a connection undefended.

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
git submodule update --init
# Install Nim 2.2.10 and Emscripten for the Polyworld browser builds.
./tools/build.sh --version VERSION
coworld certify dist/coworld_manifest.json --timeout-seconds 300
coworld upload-coworld dist/coworld_manifest.json --timeout-seconds 300
```

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
as a JSONL subprocess. Its variants are `machina-1-daily` (the default) and
`four-score-daily`. Omit `--steps` for the full published 10,000-step horizon.
The bridge accepts `reset`, `encode`, `teacher`, and `step` commands. `reset`
must name 8 players for CogsGuard/Machina 1 or 32 for Four Score.
Set Metta's `max_decisions` to at least `players * max_steps`; the published
10,000-step horizons need 80,000 or 320,000 interactions, respectively.

## Polyworld implementation

`vendor/polyworld-cogs-vs-clips` tracks the `main` branch of
[polyworld-cogs-vs-clips](https://github.com/softmax-universe/polyworld-cogs-vs-clips).
Upstream owns simulation rules, mixed-policy hosting, native images, BASIC assets,
and replay decoders. This repository owns the shared Coworld identity, manifest,
variant image selection, and combined replay bundle. Do not copy simulation code here.

| Variant | Implementation | Seats | Map |
| --- | --- | --- | --- |
| `machina-1-daily` | MettaGrid cooperative CvC | 8 | Original daily mission |
| `four-score-daily` | MettaGrid FourScore | 32 | Original daily mission |
| `polyworld-machina-daily` | Polyworld cooperative CvC | 8 | Explicit daily `map_seed` |
| `polyworld-four-score` | Polyworld FourScore | 32 | Fixed FourScore map |

Each named variant selects its compiled game through `game_runnable`. The default
runnable and certification fixture use Polyworld cooperative: one Docker reference
player and seven BASIC players complete 10,000 ticks. This exercises every bundled
player, as certification requires. Both Polyworld variants accept mixed BASIC/file
and Docker seats. The two original MettaGrid variants retain their configuration
and explicitly select the MettaGrid image; use Docker players for every seat.
`polyworld-baseline` is for Polyworld only.
Each engine retains its own observation semantics. Existing container images need
qualification against the selected Polyworld mode before league enrollment.

The upstream game owns its Coworld host and transport; no shared Polyworld transport
change is required. Both Docker modes expose the lab agents' 74-feature vocabulary,
with observer-relative Cogs/Clips teams. Dense neural file inputs remain separate.
See the upstream [qualification guide](vendor/polyworld-cogs-vs-clips/docs/cooperative-migration.md)
for the retained historical lab-image evidence and required new-build certification.

For local viewer checks, `CVC_METTAGRID_VIEWER_IMAGE=<cached-game-image>` reuses
that image's `/app/mettascope` assets. Record its digest in validation evidence.
`POLYWORLD_DEPS` may point to an existing dependency directory matching upstream's
lock. Viewer output must be a new directory; builds do not delete prior bundles.

Polyworld cooperative preserves the original 21×21 base enclosure, four five-tile
gates, corner extractors, southern gear row, and cardinal spawns. Its seeded
asteroid boundary varies daily; the outer map remains a Polyworld adaptation.

Both Polyworld viewers fit their HUD to the frame. Ctrl/Cmd +/− adjusts UI scale,
Ctrl/Cmd 0 restores automatic sizing, and F11 toggles fullscreen. Manual scale
preferences persist without changing the world camera zoom.

The shared viewer selects MettaScope, cooperative Polyworld, or FourScore Polyworld
from the recorded replay format. Unsupported Polyworld versions fail visibly.
Old uploaded Coworld versions retain their original immutable viewer bundles.

Create separate cooperative and FourScore standings. Each league must set
`commissioner_config.default_variant_id` explicitly. The cooperative Polyworld
league also requires the platform daily-map planner (`daily_map_seed: true`) and
the upstream team-score settings. The preview map seed in this manifest is fixed;
it does not implement daily scheduling by itself.

Before release, qualify all variant images: default Coworld certification exercises
the mixed cooperative fixture. Run full all-file, all-container, and mixed
Polyworld episodes, then a real Observatory round and replay check. Preserve old
league history and start fresh Polyworld standings. Publishing these sources does
not enroll policies or change league scheduling. The canonical cooperative and
FourScore leagues already use Polyworld.

`./tools/build.sh --version VERSION` refreshes the CvC submodule from `main`,
resolves Polyworld `main` once, and supplies that exact engine revision to both
native images and replay viewers. The generated manifest records the CvC commit;
`dist/dependencies.lock` records the resolved Nim dependencies. Dirty upstream
checkouts fail before updating. Rebuilds refresh dependencies without manual SHA
edits. Coworld's CLI dependency accepts releases from 0.1.69 onward. Existing
compiler and third-party Nim library pins remain unchanged.

Use this build entry point locally and in CI; direct Compose builds require the
resolved `POLYWORLD_REVISION` explicitly. Published images and replay bundles stay
immutable, and certification is still required before upload.


## Building without a CI upload credential

Dispatch `Deploy CogsGuard Coworld` with `build_only=true` and an explicit version
when `SOFTMAX_API_TOKEN` is unavailable. The runner builds and locally certifies the
same release, then retains its manifest, viewer, policy files, and compressed Docker
images for seven days. It does not upload or select a canonical Coworld.

Download the artifact into `dist/`, verify `dist/images.tar.gz.sha256`, and run
`docker load --input dist/images.tar.gz`. With your normal Softmax login, run
`coworld upload-coworld dist/coworld_manifest.json --timeout-seconds 300` and verify hosted certification.
This keeps upload credentials on the uploader's machine. Select the explicit
version using `coworld next-version cogs_vs_clips` before dispatch; check again before
upload if another release could have landed.

## League formats

All current formats share this Coworld and retain separate standings:

| Format | Policies per match | Scoring and map |
| --- | --- | --- |
| Cooperative | Eight independent Cogs | Shared team territory score; daily map |
| Singles | One policy controls all eight Cogs | Team territory score; daily map |
| Doubles | Two policies control four Cogs each | Shared team territory score; daily map |
| FourScore | Four teams of eight independent Cogs | Team competition on the fixed map |

`league-presets.json` owns the descriptions and scheduler/ranking presets. Bind each
preset to a new league's actual division before applying it. Use fresh standings
when moving from MettaGrid; preserve historical league records and replay viewers.
Daily maps are frozen from the round creation date in UTC. Singles and Doubles are
cooperative formats, so equal scores within a match must not be treated as Elo draws.

The production cadence is 288 minutes. Cooperative uses eight appearances per
entrant; Singles evaluates one complete cloned team per entrant; Doubles uses two
appearances with different sampled partners. FourScore balances team ratings and
randomizes corners and seats. Four matches do not guarantee every entrant visits
every corner; qualification explicitly rotates the four corners.

Qualify additional FourScore entrants before reducing its baseline filler seats.
Keep the existing champion for a player unless a paired comparison justifies a
replacement. Do not overwrite owners or delete their original policy artifacts.

See [CPU player defaults](coworld/game/docs/player_protocol_spec.md#cpu-player-defaults)
for uploads and the timing diagnostics used to investigate slow matches.

## Store and Play page content

`store-page.json` contains the published store content for `cogs_vs_clips`.
The generic Softmax Play page also reads its blurb. Publish edits through the
store-page draft/publish API or editor; uploading a Coworld does not publish this file.
`game.description` and variant descriptions in `coworld_manifest_template.json`
supply the game and mode summaries. Keep engine and packaging details in these
developer docs rather than the player-facing pitch.
