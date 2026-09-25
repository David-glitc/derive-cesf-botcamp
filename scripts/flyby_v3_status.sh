#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${CONTAINER:-hb-derive-py}"
ENV_FILE="${ENV_FILE:-.env}"
PYTHON_BIN="${PYTHON_BIN:-/opt/conda/envs/hummingbot/bin/python}"
LOG_FILE="${LOG_FILE:-/tmp/flyby_v3_testnet.log}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Copy .env.example to .env and fill Derive testnet values." >&2
  exit 1
fi

docker exec "$CONTAINER" pgrep -af "[r]un_flyby_v3_testnet" || true
docker exec --env-file "$ENV_FILE" "$CONTAINER" "$PYTHON_BIN" /repo/run_flyby_v3_testnet.py --status-only
docker exec "$CONTAINER" sh -lc "tail -n 80 '$LOG_FILE' 2>/dev/null || true"
