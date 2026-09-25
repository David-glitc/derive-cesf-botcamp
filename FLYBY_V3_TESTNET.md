# Flyby v3 Testnet Runbook

Use this path to demonstrate Flyby on Derive v3 testnet. Keep the Hummingbot V2 controller configs for mainnet in `controllers/` and `conf/`.

## What Runs Where

| Lane | Venue | Files | Purpose |
|---|---|---|---|
| v3 testnet | Derive v3 testnet | `run_flyby_v3_testnet.py` | Multi-asset demo, Condor decisions, real testnet orders |
| v2 mainnet adapter | Hummingbot V2 `derive` connector | `controllers/directional_trading/flyby.py`, `conf/` | Mainnet controller path |
| Research/backtest | Binance candles + Derive public options data | `backtest/`, `src/`, `agents/` | WFA, SVI, Black76, guard evidence |

## Setup

Copy the env template and fill the Derive testnet values:

```bash
cp .env.example .env
```

Expected env names:

```bash
DERIVE_SESSION_KEY=0x...
DERIVE_WALLET=0x...
DERIVE_SUBACCOUNT_ID=86301
DERIVE_ETH_CHAIN=sepolia
```

The scripts assume a container named `hb-derive-py` with `derive_py` installed in `/opt/conda/envs/hummingbot/bin/python`. Override `CONTAINER` or `PYTHON_BIN` if your environment uses different names.

## Dry Run

Run one short scan with no orders:

```bash
docker cp run_flyby_v3_testnet.py hb-derive-py:/repo/run_flyby_v3_testnet.py
docker exec --env-file .env hb-derive-py \
  /opt/conda/envs/hummingbot/bin/python /repo/run_flyby_v3_testnet.py \
  --hours 0.001 \
  --active \
  --universe ETH-PERP,BTC-PERP,SOL-PERP,HYPE-PERP,ARB-PERP,AVAX-PERP
```

Expected behavior:

- Derive native perps produce decisions.
- Unsupported symbols like `ARB-PERP` and `AVAX-PERP` log `not-listed-on-derive-v3-testnet`.
- The process exits without placing orders because `--execute` is absent.

## Live Testnet Execution

Start the multi-asset v3 runner:

```bash
bash scripts/start_flyby_v3_testnet.sh
```

Default universe:

```text
ETH-PERP,BTC-PERP,DOGE-PERP,ZEC-PERP,HYPE-PERP,SOL-PERP,BNB-PERP
```

Default guardrails:

- Scans every `60s`.
- Sends at most `2` orders per tick.
- Skips unsupported instruments.
- Uses the authenticated derive-py instrument cache for minimum sizes.
- Disables instruments after venue-level risk-universe or instrument-cache rejection.
- Skips open-order duplicates.
- Caps per-symbol exposure at `3x` the venue minimum amount.
- Skips default Condor fallback orders unless `--allow-default-orders` is supplied.

Check status:

```bash
bash scripts/flyby_v3_status.sh
```

Artifacts:

```text
hb_backtest/flyby_v3_testnet.jsonl
/tmp/flyby_v3_testnet.log inside the container
```

## Risk-universe Caveat

Derive v3 testnet enforces risk universes per subaccount. On the current testnet subaccount, ETH/BTC have executed as risk-universe-1 instruments. DOGE/ZEC/SOL/BNB may be venue-rejected if the subaccount is assigned to a different risk universe. The runner treats that as expected venue state: it logs the rejection, disables that instrument for the rest of the process, and continues scanning the remaining book.

This is the behavior we want for a public demo because another reviewer can run the same script without crashing even if their subaccount has a different universe assignment.

## Testnet Liquidity Caveat

The Derive v3 testnet perp book can be dry. Small coin amounts and resting orders should be read as venue/testnet-liquidity behavior, not as an architecture limitation. The status command reports notional exposure so reviewers can see the actual scale behind small ETH/BTC unit sizes.

## Mainnet V2 Adapter

The mainnet adapter stays on Hummingbot V2:

```bash
cp controllers/directional_trading/flyby.py <hummingbot>/controllers/directional_trading/
cp conf/controllers/*.yml <hummingbot>/conf/controllers/
cp conf/scripts/*.yml <hummingbot>/conf/scripts/
```

Then start the V2 controller from Hummingbot:

```text
create --controller-config directional_trading.flyby
start --v2 conf_v2_flyby.yml
```

This separation is intentional: v3 testnet proves Derive v3 auth and order flow, while the V2 controller remains the mainnet Hummingbot path.
