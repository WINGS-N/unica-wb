#!/usr/bin/env sh
set -eu

if [ -n "${UN1CA_ROOT:-}" ]; then
  git config --global --add safe.directory "${UN1CA_ROOT}" || true
fi

cd /app

python - <<'PY'
from app.cleanup import cleanup_stale_build_overrides

x = cleanup_stale_build_overrides()
print(
    f"[worker startup] cleanup: removed {x['uploaded_mod_dirs']} uploaded mod override dirs, "
    f"{x['tmp_extra_mods_dirs']} temp extra-mod dirs",
    flush=True,
)
PY

python -m arq app.arq_worker.WorkerSettingsBuilds &
PID_BUILDS=$!
python -m arq app.arq_worker.WorkerSettingsControls &
PID_CONTROLS=$!
echo "$PID_BUILDS" >/tmp/arq-builds.pid
echo "$PID_CONTROLS" >/tmp/arq-controls.pid

term() {
  rm -f /tmp/arq-builds.pid /tmp/arq-controls.pid
  kill -TERM "$PID_BUILDS" "$PID_CONTROLS" 2>/dev/null || true
  wait "$PID_BUILDS" "$PID_CONTROLS" 2>/dev/null || true
}

trap term TERM INT

while kill -0 "$PID_BUILDS" 2>/dev/null && kill -0 "$PID_CONTROLS" 2>/dev/null; do
  sleep 1
done

term
