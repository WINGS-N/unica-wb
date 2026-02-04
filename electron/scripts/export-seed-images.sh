#!/usr/bin/env bash
set -euo pipefail

# Генерит seed-images из локальных docker image через docker save + zstd
# Generate seed-images from local docker images via docker save + zstd

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEED_DIR="${ROOT_DIR}/seed-images"
MANIFEST_PATH="${SEED_DIR}/manifest.json"
TMP_DIR="$(mktemp -d)"
ZSTD_LEVEL="${SEED_ZSTD_LEVEL:-19}"
GHCR_OWNER="${GHCR_OWNER:-wings-n}"
SEED_REMOTE_PREFER_LATEST="${SEED_REMOTE_PREFER_LATEST:-1}"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required"
  exit 1
fi

if ! command -v zstd >/dev/null 2>&1; then
  echo "zstd is required"
  exit 1
fi

# Подхватываем IMAGE_* и GHCR_OWNER из ../.env, как в compose/publish flow
# Load IMAGE_* and GHCR_OWNER from ../.env, same as compose/publish flow
if [ -f "${ROOT_DIR}/../.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/../.env"
  set +a
fi

GHCR_OWNER="${GHCR_OWNER:-wings-n}"

repo_from_ref() {
  local ref="$1"
  ref="${ref%%@*}"
  local tail="${ref##*/}"
  if [[ "$tail" == *:* ]]; then
    echo "${ref%:*}"
  else
    echo "$ref"
  fi
}

mkdir -p "${SEED_DIR}"

# По умолчанию source берем из IMAGE_* (или :local), но в seed всегда пишем :local теги
# By default source comes from IMAGE_* (or :local), but seed always writes :local tags
if [ "$#" -eq 0 ]; then
  SOURCE_IMAGES=(
    "${IMAGE_API:-unica-wb-api:local}"
    "${IMAGE_WORKER:-unica-wb-worker:local}"
    "${IMAGE_FRONTEND:-unica-wb-frontend:local}"
  )
  LOCAL_TAGS=(
    "unica-wb-api:local"
    "unica-wb-worker:local"
    "unica-wb-frontend:local"
  )
  REMOTES=(
    "ghcr.io/${GHCR_OWNER}/unica-wb-api:latest"
    "ghcr.io/${GHCR_OWNER}/unica-wb-worker:latest"
    "ghcr.io/${GHCR_OWNER}/unica-wb-frontend:latest"
  )
else
  SOURCE_IMAGES=("$@")
  LOCAL_TAGS=()
  for source_image in "${SOURCE_IMAGES[@]}"; do
    case "${source_image}" in
      *unica-wb-api*)
        LOCAL_TAGS+=("unica-wb-api:local")
        ;;
      *unica-wb-worker*)
        LOCAL_TAGS+=("unica-wb-worker:local")
        ;;
      *unica-wb-frontend*)
        LOCAL_TAGS+=("unica-wb-frontend:local")
        ;;
      *)
        LOCAL_TAGS+=("${source_image}")
        ;;
    esac
  done
  REMOTES=()
fi

# Чистим старые архивы перед новым экспортом
# Cleanup old archives before new export
find "${SEED_DIR}" -maxdepth 1 -type f \( -name '*.tar' -o -name '*.tar.zst' \) -delete

ROWS_FILE="${TMP_DIR}/rows.tsv"
: > "${ROWS_FILE}"

for idx in "${!SOURCE_IMAGES[@]}"; do
  source_image="${SOURCE_IMAGES[$idx]}"
  local_tag="${LOCAL_TAGS[$idx]}"

  if ! docker image inspect "${source_image}" >/dev/null 2>&1; then
    echo "Image not found locally: ${source_image}"
    exit 1
  fi

  base_name="${local_tag##*/}"
  base_name="${base_name%%:*}"
  archive_name="${base_name}-local.tar.zst"
  tar_path="${TMP_DIR}/${base_name}.tar"
  out_path="${SEED_DIR}/${archive_name}"

  remote="${REMOTES[$idx]:-}"
  if [ -z "${remote}" ]; then
    if [[ "${source_image}" == *"/"* ]]; then
      remote="${source_image}"
    else
      remote="ghcr.io/${GHCR_OWNER}/${base_name}:latest"
    fi
  fi
  remote_latest="$(repo_from_ref "${remote}"):latest"
  if [ "${SEED_REMOTE_PREFER_LATEST}" = "1" ]; then
    remote="${remote_latest}"
  fi

  # Если source не :local, даем :local alias, чтобы после docker load Electron нашел local_tag
  # If source is not :local, create :local alias so after docker load Electron can find local_tag
  if [ "${source_image}" != "${local_tag}" ]; then
    docker tag "${source_image}" "${local_tag}"
  fi

  echo "Exporting ${source_image} as ${local_tag} -> ${archive_name}"
  docker save -o "${tar_path}" "${local_tag}"
  zstd -T0 -"${ZSTD_LEVEL}" -f --rm "${tar_path}" -o "${out_path}"

  size_bytes="$(wc -c < "${out_path}" | tr -d ' ')"
  sha256="$(sha256sum "${out_path}" | awk '{print $1}')"
  image_id="$(docker image inspect --format='{{.Id}}' "${source_image}")"
  created_at="$(docker image inspect --format='{{.Created}}' "${source_image}")"

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "${archive_name}" \
    "${local_tag}" \
    "${remote}" \
    "${remote_latest}" \
    "${image_id}" \
    "${created_at}" \
    "${size_bytes}" \
    "${sha256}" >> "${ROWS_FILE}"
done

python - <<'PY' "${ROWS_FILE}" "${MANIFEST_PATH}"
import json
import pathlib
import sys

rows_path = pathlib.Path(sys.argv[1])
out_path = pathlib.Path(sys.argv[2])

items = []
for raw in rows_path.read_text().splitlines():
    if not raw.strip():
        continue
    archive, local_tag, remote, remote_latest, image_id, created_at, size_bytes, sha256 = raw.split("\t")
    items.append(
        {
            "archive": archive,
            "local_tag": local_tag,
            "remote": remote,
            "remote_latest": remote_latest,
            "image_id": image_id,
            "created_at": created_at,
            "size_bytes": int(size_bytes),
            "sha256": sha256,
        }
    )

payload = {"images": items}
out_path.write_text(json.dumps(payload, indent=2) + "\n")
print(f"Wrote manifest: {out_path}")
PY

echo "Seed export done"
echo "Manifest: ${MANIFEST_PATH}"
echo "Archives dir: ${SEED_DIR}"
