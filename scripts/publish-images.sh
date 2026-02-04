#!/usr/bin/env bash
set -euo pipefail

# Быстрый publish образов через docker compose build + push
# Quick image publish via docker compose build + push

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [ -f .env ]; then
  # Подхватываем IMAGE_* и GHCR_OWNER из .env если есть
  # Load IMAGE_* and GHCR_OWNER from .env when file exists
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

GHCR_OWNER="${GHCR_OWNER:-wings-n}"
IMAGE_API="${IMAGE_API:-ghcr.io/${GHCR_OWNER}/unica-wb-api:latest}"
IMAGE_WORKER="${IMAGE_WORKER:-ghcr.io/${GHCR_OWNER}/unica-wb-worker:latest}"
IMAGE_FRONTEND="${IMAGE_FRONTEND:-ghcr.io/${GHCR_OWNER}/unica-wb-frontend:latest}"

export IMAGE_API IMAGE_WORKER IMAGE_FRONTEND

echo "Publishing images with tags:"
echo "  IMAGE_API=${IMAGE_API}"
echo "  IMAGE_WORKER=${IMAGE_WORKER}"
echo "  IMAGE_FRONTEND=${IMAGE_FRONTEND}"

docker compose -f docker-compose.yml build api worker frontend
docker compose -f docker-compose.yml push api worker frontend

echo "Publish done"
