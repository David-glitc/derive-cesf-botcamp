# Flyby Submission Positioning

This note turns the public Botcamp/Hummingbot/Derive rules and public builder landscape into the submission angle for Flyby.

## Public Rules and Judging Context

| Public signal | What it means for Flyby |
|---|---|
| Agent Builders Cup accepts Hummingbot V2 Controllers and Condor Agents | Lead with the V2 controller plus Condor agent architecture. |
| Derive is one of the sponsor teams | Lead with Derive-native options, SVI, Black76, and margin-aware risk. |
| Finals are 48h and start from $800 per agent | Keep 1h decisions, hard caps, and unattended run scripts visible. |
| Public leaderboard surfaces include P&L, volume, and HBOT vote | Explain both return logic and safe order generation. Make the story easy to understand. |
| Finals format requires unattended bot operation | Show `scripts/start_flyby_v3_testnet.sh`, `scripts/flyby_v3_status.sh`, no-crash unsupported-symbol handling, and logs. |

## Public Landscape

Public Botcamp builder material shows many agents framed as market makers, LP/range managers, inventory controllers, funding-aware strategies, or general Condor trading agents. Full public Derive-specific code submissions are sparse from public GitHub search, so the strongest comparison is by strategy type rather than exact repository-by-repository claims.

Flyby should be described as a Derive volatility submission:

- It treats Derive as an options and volatility venue.
- It uses SVI and Black76 as the center of the trading edge.
- It has a crash/event filter before it pays option premium.
- It keeps deterministic execution and risk controls even when Condor chooses the regime.
- It demonstrates v3 testnet auth/order flow while preserving the V2 mainnet controller path.

## Submission Claim

Flyby is the Derive-native volatility specialist in the field: a Condor-controlled, Hummingbot-executable agent that prices Derive volatility, filters for event mass, sizes with Kelly, and enforces portfolio guards before it places orders.

## Recommended Short Pitch

Flyby buys cheap volatility only when the event structure says the move is real. It fits Derive because it uses the options surface directly: SVI for implied vol, Black76 for premium, CESF crash-mass for timing, and Kelly plus PortfolioGuard for sizing. The v3 testnet runner proves live testnet Derive order flow now, while the Hummingbot V2 controller remains the mainnet Botcamp path.

## Reviewer-facing Strengths

| Strength | Proof to point at |
|---|---|
| Derive-native strategy | `src/svi/`, `src/pricing/black76.py`, `src/venue/derive.py` |
| Condor integration | `agents/condor_agent.py` |
| Hummingbot V2 compatibility | `controllers/directional_trading/flyby.py`, `conf/` |
| Live/testnet order proof | `run_flyby_v3_testnet.py`, `hb_backtest/flyby_v3_testnet.jsonl` |
| Setup by another person | `.env.example`, `scripts/start_flyby_v3_testnet.sh`, `scripts/flyby_v3_status.sh`, `FLYBY_V3_TESTNET.md` |
| No-crash behavior | Unsupported/risk-universe instruments are logged, disabled, and skipped. |
| Risk discipline | `src/risk/portfolio_guard.py`, hard caps in the runner |
| Research evidence | `backtest/`, plots, WFA table in `strategy.md` |

## Risk-universe Note

The current Derive v3 testnet subaccount is risk-universe constrained. ETH/BTC orders can execute on the current subaccount; instruments assigned to another risk universe may be rejected by the venue. Flyby handles this by disabling the rejected instrument and continuing the run. That is the behavior to show judges: broad scan, real venue checks, no process crash.

## Testnet Liquidity Note

Derive v3 testnet perp liquidity can be thin. Use the live run as proof that Flyby authenticates, reads markets, creates orders, tracks positions, reports notional exposure, and survives venue rejections. Do not sell the testnet run as proof of production fill quality.

## Wording to Use

Use:

> Flyby scans the Derive v3 testnet universe, executes supported instruments for the current subaccount, and safely disables venue-rejected instruments without crashing.

Avoid:

> Flyby live-trades every listed Derive market from any subaccount.

Use:

> ARB, AVAX, and OP are research/proxy assets unless Derive lists and supports them for the active account.

Avoid:

> ARB, AVAX, and OP are live Derive execution assets.

## Sources

- Hummingbot v2.16.0 release notes: Agent Builders Cup sponsor/team format, V2 Controller or Condor Agent eligibility, Derive sponsor, prize pool, and 48h finals. <https://hummingbot.org/release-notes/2.16.0/>
- Botcamp Agent Builders Cup public page: starting capital, eligible exchanges, public ranking surfaces, timeline, and Derive team page. <https://www.botcamp.xyz/hackathons/agent-builders-cup-1>
- Hummingbot September 2026 newsletter: finalist format, Derive workshop context, and Derive v2.17 configuration note. <https://hummingbot.substack.com/p/hummingbot-newsletter-september-2026>
- Hummingbot Condor quickstart: Condor as LLM decision layer with deterministic execution through Hummingbot. <https://hummingbot.org/installation/condor/>
- Hummingbot Condor introduction: Observe, Orient, Decide, Act framing and deterministic Act layer. <https://hummingbot.org/blog/introducing-condor-the-open-source-harness-for-trading-agents/>
