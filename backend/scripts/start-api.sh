#!/usr/bin/env sh
set -eu

if [ -n "${UN1CA_ROOT:-}" ]; then
  git config --global --add safe.directory "${UN1CA_ROOT}" || true
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers
