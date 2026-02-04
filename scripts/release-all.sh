#!/usr/bin/env bash
set -euo pipefail

# Полный release pipeline: build images -> export seed -> build electron -> publish images
# Full release pipeline: build images -> export seed -> build electron -> publish images

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ELECTRON_DIR="${ROOT_DIR}/electron"

ELECTRON_TARGET="${1:-linux}"
PUBLISH_MODE="${PUBLISH_MODE:-yes}"

case "${ELECTRON_TARGET}" in
  linux|win|windows|all)
    ;;
  *)
    echo "Unknown electron target: ${ELECTRON_TARGET}"
    echo "Use one of: linux | win | all"
    exit 1
    ;;
esac

if [ -f "${ROOT_DIR}/.env" ]; then
  # Подхватываем IMAGE_* и GHCR_OWNER из .env
  # Load IMAGE_* and GHCR_OWNER from .env
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi

echo "[1/4] Build docker images via compose"
(
  cd "${ROOT_DIR}"
  docker compose -f docker-compose.yml build api worker frontend
)

echo "[2/4] Export seed images"
(
  cd "${ELECTRON_DIR}"
  ./scripts/export-seed-images.sh
)

echo "[3/4] Build electron packages via docker (${ELECTRON_TARGET})"
(
  cd "${ELECTRON_DIR}"
  ./scripts/build-docker.sh "${ELECTRON_TARGET}"
)

if [ "${PUBLISH_MODE}" = "yes" ]; then
  echo "[4/4] Publish docker images"
  (
    cd "${ROOT_DIR}"
    ./scripts/publish-images.sh
  )
else
  echo "[4/4] Publish skipped (PUBLISH_MODE=${PUBLISH_MODE})"
fi

echo "Release pipeline done"
echo "Electron artifacts: ${ELECTRON_DIR}/out"
