#!/usr/bin/env bash
set -euo pipefail

# Full release pipeline: build images -> export seed -> build the desktop
# launcher -> publish images

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_DIR="${ROOT_DIR}/desktop"

VERSION="${VERSION:-0.0.0}"
PUBLISH_MODE="${PUBLISH_MODE:-yes}"

if [ -f "${ROOT_DIR}/.env" ]; then
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
  cd "${ROOT_DIR}"
  ./scripts/export-seed-images.sh
)

echo "[3/4] Build the desktop launcher (${VERSION})"
(
  cd "${DESKTOP_DIR}"
  VERSION="${VERSION}" task package
)

if [ "${PUBLISH_MODE}" = "yes" ]; then
  echo "[4/4] Publish images"
  (
    cd "${ROOT_DIR}"
    ./scripts/publish-images.sh
  )
else
  echo "[4/4] Publish skipped (PUBLISH_MODE=${PUBLISH_MODE})"
fi

echo
echo "Release done"
echo "Desktop artifacts: ${DESKTOP_DIR}/dist"
