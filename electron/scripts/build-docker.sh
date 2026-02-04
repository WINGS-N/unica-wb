#!/usr/bin/env bash
set -euo pipefail

# Скрипт делает сборку Electron через Docker, на хосте нужен только docker CLI
# Script builds Electron via Docker, host machine needs only docker CLI

TARGET="${1:-linux}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WB_ROOT="$(cd "${ROOT_DIR}/.." && pwd)"
OUT_DIR="${ROOT_DIR}/out"
IMAGE_TAG="unica-wb-electron-builder:local"

case "${TARGET}" in
  linux)
    BUILD_CMD="pnpm install --no-frozen-lockfile && pnpm run pack:linux"
    ;;
  linux-no-seed)
    BUILD_CMD="pnpm install --no-frozen-lockfile && pnpm run pack:linux:no-seed"
    ;;
  win|windows)
    BUILD_CMD="pnpm install --no-frozen-lockfile && pnpm run pack:win"
    ;;
  all)
    BUILD_CMD="pnpm install --no-frozen-lockfile && pnpm run pack:linux && pnpm run pack:win"
    ;;
  *)
    echo "Unknown target: ${TARGET}"
    echo "Use one of: linux | linux-no-seed | win | all"
    exit 1
    ;;
esac

mkdir -p "${OUT_DIR}"

# Отдельный image нужен для кеша corepack/pnpm внутри контейнера и повторяемых сборок
# Separate image keeps corepack/pnpm setup and makes repeat builds faster
docker build -f "${ROOT_DIR}/Dockerfile.builder" -t "${IMAGE_TAG}" "${ROOT_DIR}"

# Кладем результаты в out, это единая папка артефактов для desktop сборки
# Put artifacts to out, this is single artifact folder for desktop builds
DOCKER_CMD="
set -euo pipefail
cd /workspace/electron
${BUILD_CMD}
mkdir -p /out
rm -rf /out/*
if [ -d dist ]; then
  cp -a dist/. /out/
fi
"

docker run --rm \
  -v "${WB_ROOT}:/workspace" \
  -v "${OUT_DIR}:/out" \
  -v unica-wb-electron-pnpm-store:/root/.local/share/pnpm/store \
  -v unica-wb-electron-cache:/root/.cache/electron \
  -v unica-wb-electron-builder-cache:/root/.cache/electron-builder \
  "${IMAGE_TAG}" \
  "${DOCKER_CMD}"

echo "Build done. Artifacts: ${OUT_DIR}"
