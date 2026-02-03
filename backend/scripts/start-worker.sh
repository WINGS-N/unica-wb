#!/usr/bin/env sh
set -eu

if [ -n "${UN1CA_ROOT:-}" ]; then
  git config --global --add safe.directory "${UN1CA_ROOT}" || true
fi

exec python worker.py
