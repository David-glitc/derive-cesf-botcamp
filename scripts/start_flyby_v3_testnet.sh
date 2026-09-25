#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${CONTAINER:-hb-derive-py}"
ENV_FILE="${ENV_FILE:-.env}"
PYTHON_BIN="${PYTHON_BIN:-/opt/conda/envs/hummingbot/bin/python}"
LOG_FILE="${LOG_FILE:-/tmp/flyby_v3_testnet.log}"
HOURS="${HOURS:-5}"
TICK_SECONDS="${TICK_SECONDS:-60}"
MAX_ORDERS_PER_TICK="${MAX_ORDERS_PER_TICK:-2}"
UNIVERSE="${UNIVERSE:-ETH-PERP,BTC-PERP,DOGE-PERP,ZEC-PERP,HYPE-PERP,SOL-PERP,BNB-PERP}"
EXTRA_ARGS="${EXTRA_ARGS:-}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Copy .env.example to .env and fill Derive testnet values." >&2
  exit 1
fi

docker cp run_flyby_v3_testnet.py "$CONTAINER:/repo/run_flyby_v3_testnet.py"
docker exec "$CONTAINER" pkill -f "run_flyby_v3_testnet.py" >/dev/null 2>&1 || true

docker exec --env-file "$ENV_FILE" "$CONTAINER" sh -lc \
  "nohup $PYTHON_BIN -u /repo/run_flyby_v3_testnet.py \
    --execute \
    --active \
    --hours '$HOURS' \
    --tick-seconds '$TICK_SECONDS' \
    --max-orders-per-tick '$MAX_ORDERS_PER_TICK' \
    --universe '$UNIVERSE' \
    $EXTRA_ARGS \
    > '$LOG_FILE' 2>&1 & echo \$!"

echo "Started Flyby v3 testnet runner in $CONTAINER"
echo "Log: $LOG_FILE"
