# Run Flyby local validation

Run unit, model-proof, historical-diagnostic and optional public-data checks
without starting a bot. Read the [evidence report](../reports/SHADOW_VALIDATION_REPORT.md)
before interpreting passing checks as live readiness.

## Install the optional solver locally

From the repository root, use your research environment with the
[Python dependencies](../requirements.txt) installed. Keep Z3 out of running bots:

```bash
python3 -m pip install --target .local_harness/verification-deps z3-solver==4.16.0.0
```

Expected: Z3 4.16.0 installs in the ignored local harness directory. The package
also provides a `verification` optional dependency for dedicated environments.
The checker uses [Z3's solver API](https://microsoft.github.io/z3guide/programming/Z3%20Python/Introduction/)
to seek violations of each declared model property.

## Run the validation bundle

1. Choose a new output directory. Existing evidence isn't overwritten.
2. Run the bundle:

   ```bash
   PYTHONPATH=.local_harness/verification-deps python3 scripts/validate_flyby.py \
     --output data/validation/full-build-20261002 --with-hummingbot \
     --historical-data data/stress-candles --public-samples 2
   ```

   Expect ten stages, `checks_passed: true`, `live_ready: false` and
   `profitability_proven: false` on the verified environment. Choose another
   output name if this example's directory already exists.

3. Inspect `validation.json`, stage logs, `formal.json`, `delta.json`, `comparison/` and the
   ETH/BTC archives/replays. Each stage records its command, duration and exit
   code. Missing solver/data, a failed request or a failed test produces a
   nonzero overall exit status.

Docker and the pinned image are prerequisites for `--with-hummingbot`.
For real Condor registry/tick checks, add `--condor-root` with your official
checkout and `--condor-python` with that environment's interpreter. This adds
one mocked-transport stage, not a provider-backed or live exchange test.
Previously downloaded histories are prerequisites for `--historical-data`;
the runner doesn't download or invent historical option chains. Omit those
flags for unit/model-only checks. `--public-samples` defaults to zero, allows
at most six samples per currency and doesn't publish shadow files.

## Interpret model verification

Finite exploration runs the actual pure paired reducer up to three integer
lots, including overfills, mismatches, terminal/partial reports and timeouts.
Six SMT obligations cover matched-fill/close bounds, reservations, reduce-only
intent, entry guards and idealized notional caps. Two unsafe mutations must
produce counterexamples. A solver `unknown` is a failure.

These exact integer/rational models exclude Python float rounding, process
concurrency, signing/RPC, real margin, exchange fills and profitability. The
paired model has no submission method and rejects live modes. External
unmatched reports halt and preserve the fault/reservation; that isn't proof
that a venue cannot create unmatched exposure.

## Inspect native context safely

Use [bounded native capture](../backtest/NATIVE_DATA.md) with `--quant` for
public WS L2, deduplicated recent prints, tenor IV/skew/OI and costed spread
scenarios. Depth isn't matching proof; recent VWAP/POC isn't a complete tape.
CVD and signed dealer GEX remain unknown. Candidate scenarios have no
calibrated probabilities; `entry_authorized` stays false.

For fixture/shadow testing, `signal_source: derive_native` opts the existing
controller into an owned native 5m snapshot. It never falls back to Binance
when native context expires. Submitted profiles retain `binance_proxy`, kill
switches and disabled live options. Native ticks expire after five seconds,
so a bounded 20-second sample interval isn't a production continuous feed.

## Resolve failed checks

| Failure | Action |
|---|---|
| `ModuleNotFoundError: z3` | Install the pinned local solver and set `PYTHONPATH` as above |
| Existing output directory | Choose a new name; preserve earlier evidence |
| Missing historical CSVs | Supply diagnostic data or omit historical comparison |
| Public sample failure | Inspect logs/partial raw archive; retry boundedly in a new directory |
| Unexpected SAT / `unknown` | Treat the proof as failed; inspect formula hashes/counterexamples |
| Native context expired | Keep entries disabled; don't loosen freshness gates |

Real routing still requires the approved execution contract and separate
exchange validation. See [live readiness](../COMPETITION_READINESS.md).
No check accesses credentials, starts an agent, patches a running connector
or submits an order.

The Condor verifier constructs an isolated TickEngine and invokes one `_tick`
with mocked API/providers/model and blocked network connections. It doesn't
start the lifecycle supervisor or an existing deployment. Saved-config upserts
remain outside upstream's dry-run refusal policy, so the playbook—not a complete
sandbox—prohibits those calls. See [Condor installation](../condor/INSTALL.md).

## Check the delta sizing model separately

With the optional local solver installed, choose a new output filename:

```bash
PYTHONPATH=.local_harness/verification-deps python3 verification/check_delta.py --output data/validation/delta-bound-review.json
```

Expected: call, put and gross checks report `unsat`, with `passed: true` and
`live_ready: false`. The bundle now runs this checker as `formal_delta` and
records its source hash. It proves real-valued exposure inequalities
for same-kind option legs and bounded partial quantities, not implementation
equivalence, exchange matching, fees/margin or a maximum-loss guarantee.
An unmatched short option remains prohibited. See the
[delta evidence](../reports/DELTA_OPTIONS_REPORT.md).
