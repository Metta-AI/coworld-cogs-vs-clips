#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$(python3 -c 'import pathlib, sys; print(pathlib.Path(sys.argv[1]).resolve())' "$1")"

if [[ "${output_dir}" != "${repo_dir}/"* ]]; then
  echo "unsafe replay viewer output: ${output_dir}" >&2
  exit 1
fi

rm -rf "${output_dir}"
mkdir -p "${output_dir}"

image_tag="cogs-vs-clips-replay-viewer-build:$$"
container_id=""
cleanup() {
  if [[ -n "${container_id}" ]]; then
    docker rm --force "${container_id}" >/dev/null 2>&1 || true
  fi
  docker image rm --force "${image_tag}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker build \
  --platform linux/amd64 \
  --file "${repo_dir}/Dockerfile.game" \
  --target replay-viewer-bundle \
  --tag "${image_tag}" \
  "${repo_dir}"
container_id="$(docker create "${image_tag}")"
docker cp "${container_id}:/index.html" "${output_dir}/index.html"
docker cp "${container_id}:/mettascope" "${output_dir}/mettascope"

test -f "${output_dir}/index.html"
