#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$(python3 -c 'import pathlib, sys; print(pathlib.Path(sys.argv[1]).resolve())' "$1")"
if [[ -e "${output_dir}" ]]; then
  echo "Replay viewer output already exists: ${output_dir}" >&2
  exit 1
fi
mkdir -p "${output_dir}/mettagrid"

built_image=""
container_id=""
cleanup() {
  if [[ -n "${container_id}" ]]; then
    docker rm --force "${container_id}" >/dev/null
  fi
  if [[ -n "${built_image}" ]]; then
    docker image rm "${built_image}" >/dev/null
  fi
}
trap cleanup EXIT

# An explicit cached runtime image avoids rebuilding unchanged MettaScope assets.
if [[ -n "${CVC_METTAGRID_VIEWER_IMAGE:-}" ]]; then
  viewer_image="${CVC_METTAGRID_VIEWER_IMAGE}"
  viewer_path=/app/mettascope
else
  built_image="cogs-vs-clips-replay-viewer-build:$$"
  viewer_image="${built_image}"
  viewer_path=/mettascope
  docker build --load \
    --platform linux/amd64 \
    --file "${repo_dir}/Dockerfile.game" \
    --target replay-viewer-bundle \
    --tag "${built_image}" \
    "${repo_dir}"
fi
container_id="$(docker create "${viewer_image}")"
docker cp "${container_id}:${viewer_path}" "${output_dir}/mettagrid/mettascope"
cp "${repo_dir}/replay-viewer/index.html" "${output_dir}/mettagrid/index.html"

# The upstream owns both Polyworld simulations and their replay routing.
upstream="${repo_dir}/vendor/polyworld-cogs-vs-clips"
if [[ -n "${POLYWORLD_REVISION:-}" || -z "${POLYWORLD_DEPS:-}" ]]; then
  python3 "${upstream}/tools/setup_dependencies.py"
  export POLYWORLD_DEPS="${upstream}/.deps"
fi
"${upstream}/coworld/tools/build_replay_viewer.sh" "${output_dir}/polyworld" both
cp "${repo_dir}/replay-viewer/shared.html" "${output_dir}/index.html"
