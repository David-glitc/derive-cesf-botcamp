# HB Condor Derive V3 Testnet Proof

Run date: 2026-09-24 UTC / 2026-09-25 CEST

Script: `run_hb_v3_live.py`
Pair: `ETH-PERP`
Venue: Derive v3 testnet
Agent regime: `scalp-long-put-atm`

## Result

The patched HB Condor live runner authenticated to Derive v3 testnet, produced live Condor decisions, and submitted a filled testnet order.

Evidence:

- `hb_backtest/v3_live_fast.log`
- `hb_backtest/v3_live_log.jsonl`

Filled order:

- Timestamp: `2026-09-24 23:31:06` UTC
- Instrument: `ETH-PERP`
- Amount: `0.01`
- Order ID: `001614a4-518e-4f3a-bfe9-a3ec91a8bdf0`
- Filled amount in log: `0.01`

## Fix Applied During Test

The earlier five minute live run reached tick 6 but the order call returned `connection lost`. The runner was using blocking `time.sleep()` inside an async WebSocket client, which prevented the event loop from servicing the socket between ticks.

`run_hb_v3_live.py` now uses `await asyncio.sleep(...)` and retries the order once after reconnecting if the socket drops at submit time. The follow-up proof run used 30 second ticks and placed the filled order above.
