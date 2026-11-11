#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ "$#" != 2 || "$1" != --version ]]; then
  echo 'Usage: tools/build.sh --version VERSION' >&2
  exit 1
fi

upstream=vendor/polyworld-cogs-vs-clips
if [[ -e "$upstream/.git" && -n "$(git -C "$upstream" status --porcelain --untracked-files=normal)" ]]; then
  echo "Refusing to update a modified upstream checkout: $upstream" >&2
  exit 1
fi
git submodule update --init --remote -- "$upstream"
export POLYWORLD_REVISION
POLYWORLD_REVISION="$(git ls-remote https://github.com/softmax-universe/polyworld.git refs/heads/main | cut -f1)"
test -n "$POLYWORLD_REVISION"
export POLYWORLD_DEPS="$PWD/$upstream/.deps"
python3 "$upstream/tools/setup_dependencies.py"

coworld build --version "$2"

# Source URLs describe the bytes just built, even when main advances afterward.
python3 - <<'PY'
import json
import subprocess
from pathlib import Path

upstream = Path('vendor/polyworld-cogs-vs-clips')
revision = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
path = Path('dist/coworld_manifest.json')
manifest = json.loads(path.read_text())
source = 'https://github.com/softmax-universe/polyworld-cogs-vs-clips/tree/'
runnables = [manifest['game']['runnable']]
runnables.extend(v['game_runnable'] for v in manifest['variants'] if 'game_runnable' in v)
for runnable in runnables:
    if runnable['source_url'].startswith(source):
        runnable['source_url'] = source + revision
path.write_text(json.dumps(manifest, indent=2) + '\n')
Path('dist/dependencies.lock').write_bytes((upstream / '.deps/dependencies.lock').read_bytes())
PY
