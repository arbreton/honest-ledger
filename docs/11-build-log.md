# 11 — Build log: what exists, what changed from the design, what is next

Date: 2026-11-08 · Operator decisions this session: stop v1; build v2; **$66 with no monthly contributions** (RFC D1 = $0); reuse the v1 hot-wallet key for the v2 signer.

## What is built and tested (47 tests: 39 offline + 8 against a local mainnet fork)

| Layer | Modules | Proof |
|---|---|---|
| Truth | `ledger`, `chain` (indexer), `reconcile`, `nav`, `prices`, `registry` | 22 txs rebuilt from nonce 0; ledger = chain to the wei; code hashes pinned |
| Safety | `rules` (R-01..R-21), `halt`, `auditor/` (independent), canaries | 18 attack scenarios + control; tamper tests |
| Money path | `planner`, `sim` (anvil fork), `executor`, `signer/` | Full path on a fork: approve+deposit confirmed, exact allowance consumed, no residual |
| Judgement | `strategies`, `airdrops`, `forecasts`, `yields` | Do-nothing is the output unless payback is proven |
| Surface | `notify` (Telegram + outbox), `report`, `site`, dashboard | Live at the existing address |

## Deviations from the design docs (and why)
1. **Signing via `cast mktx`**, not custom code (ADR-0015). The LLD's Ed25519 receipts are HMAC in S0, as the LLD allowed.
2. **No separate OS users** (needs sudo). Honest S0 limit documented in ADR-0015 and `ops/HARDENING.md`.
3. **Cost rules use the expected gas price; R-05 bounds the worst case.** Found by the pipeline test: pricing at the cap would have made v2 reject its own $2 deposit.
4. **Ledger invariant is per-asset quantity**, not USD (LLD §3 updated).
5. **Free-RPC limit:** `eth_getLogs` needs an address filter, so unknown tokens arriving in the wallet are not seen; known-token outflows are still caught by exact balance reconciliation. A paid RPC at S1 closes it.
6. **Fork simulation runs without `--optimism`** and retries receipts (the local miner is async).
7. **Telegram is optional** until you create a bot; alerts always land in `data/outbox.log`.

## Findings made by the system itself
- **Correction (same day):** I first reported the held Morpho vault at 0.5%/yr, unreconciled with DeFiLlama's 5%. That was my error: I converted days to blocks assuming 43,200 blocks/day, but Base now makes 5 blocks/s (0.2 s blocks), so my "30-day" window was really about 3 days. Measured over real time (`farmv2/timeutil.py`, block timestamps) the vault pays **5–6%/yr**, matching DeFiLlama. All time windows now use timestamps.
- LP is **trailing holding by $0.02** after $0.58 of fees (was +$0.13 yesterday), 292 ticks (about 2.9%) from its lower edge, with a dead gauge.
- Corrected earlier errors: v1's "Morpho gas" and "5.5% APY" were artifacts (docs/00 F-17).

## Realistic expectations at $66 with $0 contributions
At 5% net, a year earns about $3. Reaching $100,000 is arithmetic, not a forecast: more than 50 years at 15% with no new money (docs/01). The system's job at this size is to **not lose money to avoidable mistakes** (v1 lost $3.85 to one), measure honestly, hold cheap airdrop options without chasing them, and be ready if capital ever grows. It does not pretend otherwise.

## Operating it
```
ops/setup-signer.sh      # you: import v1 key into encrypted keystore (asks passphrase, shows allowlist to approve)
ops/unlock-signer.sh     # you: unlock (after every reboot); ops/lock-signer.sh to lock
ops/install-timer.sh     # you: 15-min tick + 1-min Telegram poll timers (--remove to undo)
ops/setup-telegram.sh    # you: connect a NEW bot (alerts, /status /halt /approve /deny)
python3 -m farmv2 canary-live   # you, once, after unlock: wrap+unwrap ~$0.50 through the whole pipeline on mainnet
python3 -m farmv2 status | considered | forecasts | halt | resume --yes
```

## Next
1. Operator: run the four setup steps above; then `canary-live` to prove the path on mainnet.
2. 14 days of unlocked-but-idle operation (the real shadow period) before any new strategy goes live.
3. Decide the LP (exit to ETH/USDC vs keep) after seeing another week of fee-vs-hold data.
4. S1 work (only at about $1,000 NAV): Safe + Roles, paid RPC, range-managed LP, incentive harvesting.


## Addendum: LP management (2026-11-08, operator: "approve all")
- Built `lp.py` (exit/recenter plans), `lp-manage` trigger strategy, standing approvals, internal-rebalance limits, simulation probe, and `ops/approve-allowlist.sh`.
- Verified on-chain, not from memory: the mint selector matches v1's real mint tx; the swap router was found as the top swapper on our pool and its factory matches. A remembered router address was wrong (different factory) and was rejected.
- Proof: both plans simulated against the REAL wallet and position on a mainnet fork (value preserved to the cent); full 10-transaction recenter executed through executor -> signer on a fork for a throwaway wallet holding a copy of the NFT; 71 tests pass.
- **Pending operator step:** `ops/approve-allowlist.sh --yes` (the system correctly refused to let the assistant widen its own signing permissions). Until then LP actions are gated off and the dashboard says so.
- Test lesson: tests must not depend on live wallet balances (the strategy parked the USDC a test had been borrowing).
- Measured: 7-day LP fee run-rate $0.053/day (63% APR gross); pool had 4,743 swaps in 22 h.

## Addendum: research lab, risk menu, micro-caps (2026-11-09)
Operator asked to "implement all risks", test technical analysis and ML, and leave backtesting running to find a winning formula.
- **Built `lab/`** (isolated venv with numpy/pandas/scikit-learn; no keys, no signer access; the money path stays stdlib-only): TA library, 542 rule-based configs (spot long-only, 1x long/short perp, 2x/3x/5x leveraged), 72 walk-forward ML configs (logistic, gradient boosting, random forest), a backtester with costs, perp funding and a **fixed-margin perp account with intrabar liquidation**, and anti-overfitting statistics (deflated Sharpe, stationary-bootstrap reality check, parameter-plateau test).
- **Method:** identical windows (select 2023-24, validate 2025, holdout 2026 touched once for survivors only). Gates: beat buy-and-hold risk-adjusted in both windows, no liquidation, deflated Sharpe >= 0.90 against ALL trials, parameter plateau, turnover <= 250/yr.
- **Result (614 trials): 0 survivors; reality-check p = 1.00.** Only 2% of strategies beat buy-and-hold in the 2023-24 bull, 46% in 2025, 52% in 2026: most "wins" are being out of a falling market. ML had NEGATIVE median edge vs buy-and-hold (-0.34 / -0.19 Sharpe). 71 leveraged configs were liquidated; a 2x-5x long of ETH is wiped out within 2022. Best runner-ups: 60-day momentum (long/short), deflated Sharpe only ~0.1.
- **Forward paper trading:** 11 strategies registered 2026-11-09 02:00 UTC (8 pre-registered baselines incl. a 3x "real risk" case, plus 3 sweep runner-ups). Only bars after registration count. 30 days minimum before any review; hourly via the existing tick, weekly sweep in the background (no new timers).
- **Micro-cap study (Aerodrome new pools, 4 days):** 95 pools created, 18 priceable, ~0 positive after a 3% round-trip cost, one 24h rug (-100%). Thin sample, upper bound (honeypots undetectable), and Aerodrome is not where memecoins mostly launch (Uniswap v4/Clanker/Zora would need their own collectors).
- **LP resize** (`python3 -m farmv2 lp-resize --eth 0.0095 [--yes]`): wraps idle ETH and re-mints the LP at +/-8% with the larger balance; tested end-to-end on a fork; NOT executed. It cuts ETH exposure from ~87% to ~50%, which contradicts a "rally" thesis. The signer's 20-tx/day cap means a trigger recenter and a resize cannot happen the same day.
- **Not built, by design:** no live leverage or perp venue integration (no evidence of edge; the signer cannot sign it), no live micro-cap buying.

## Addendum: the operator's technical-analysis questions, answered with tests (2026-11-09)
Asked: RSI, Bollinger, EMA, SMA, Fibonacci, weekly trends, "always jumps on the weekly", "always sells at the Asia open", a runner when weekly/monthly is red, and cycle tops/bottoms ("early stock with 8x").
- **Already covered:** RSI, Bollinger (reversion + breakout), EMA, SMA, MACD, Donchian, momentum, as strategies and as ML inputs (+ hour-of-day/day-of-week as features).
- **Added and tested:** Fibonacci retracements (24 configs, causal swing pivots), weekly-bar trends (SMA, breakout, weekly-open bias, previous-week direction), session/calendar hypotheses (12+4), RUNNER (36 configs: keep r in {0,.1,.25,.5} when weekly/monthly trend is red), CYCLE runner (8 configs), ML feature set v2 (+Fibonacci, weekly, session). **790 trials; 0 survivors; reality-check p = 1.00.** No-lookahead truncation tests pass for every new family.
- **Raw pattern tests (`lab/seasonality.py`):** no hour of day or weekday survives Bonferroni correction. Asia open (00-02 UTC): down on 49% of days, p = 0.28, sign flips by year. Weekly: 48% of 255 weeks up; last week vs this week rank corr +0.10 (n.s.); Monday does not predict the week. Volume (not direction) peaks 13-16 UTC. A bug found on the way: pandas ignores `origin` on tz-aware indexes, so the first weekly run used the wrong week boundaries; fixed and rerun.
- **ML:** 12 walk-forward models, rank IC between -0.021 and +0.033 (mean +0.008); accuracy 49.7-53.1% vs a 51% majority baseline. The new features did not help. 144 ML configs, none robust.
- **Runner:** leaving a runner raises participation (median Sharpe 2023-24: +0.78 at r=0, +1.04 at r=0.5) but does not fix drawdowns or pass the gates; monthly 3-SMA with r=0 was the best defensive version in 2025-26.
- **Cycle runner:** the ONLY family that beat buy-and-hold in all three windows (8/8 configs, 100% plateau, smaller drawdowns) but deflated Sharpe ~0.00-0.01: it was designed after looking at ~3 cycles, so the sweep cannot separate it from luck. Registered for forward paper trading with 3 sibling ideas (4 new paper accounts, 15 total).
- **Cycles (`lab/cycles.py`, daily data since 2017):** ETH is 56% below its Aug-2025 high ($4,832), Mayer 0.99. Cycle multiples compress (2018 bottom to 2021 top ~57x; 2022 bottom to 2025 top ~4.9x; ATH to ATH 2021->2025 ~1.0x). An 8x from here ($17,020) is 3.5x the old high. In "similar" past conditions the next 365 days ranged from -75% to +54% over ~5 independent episodes: no dependable signal.
- **Operations:** the LP resize executed (11 txs, ~$0.02 fees, LP now ~$51.6 at +/-8%, NAV unchanged). A sweep crash (list-valued parameter in the plateau test, then a missing `fs` key) cost one 12-minute training run; walk-forward outputs are now cached and `neighbours()` is tested on every config.

## Addendum: forward paper trading started (2026-11-09)
* 15 paper accounts registered (cohorts 02:00 and 03:00 UTC); updated hourly by the existing 15-minute tick; weekly sweep in the background.
* `docs/12-forward-test-plan.md` pre-registers the day-30 / day-90 / day-180 rules BEFORE any forward result exists (sha256 recorded in `data/lab.db`, table `prereg`). Day 30 (2026-12-09) is a sanity screen only; nothing is promoted before day 90, and nothing goes live before day 180 and then only as a $5 spot canary.
* `lab/review.py` writes `docs/reviews/paper-day30-2026-12-09.md` by itself when the first cohort reaches 30 days, adds a line to `data/outbox.log`, and the dashboard shows a "day N of 30" counter. Tested (2 tests).

## Addendum: publication and the opportunity pipeline (2026-11-09)
* Personal values (wallet address, Netlify site id) moved to the git-ignored `registry-data/local.json`; the committed registry carries a placeholder wallet. `registry.load()` merges the override; `pin_all` writes only the committed file.
* Added `pipeline/` (stdlib, runs inside the existing 15-minute tick every 6 h): Superteam Earn + Immunefi + Base funding-page watcher, expected-$/hour ranking, draft packets from verifiable profile facts, deadline and lead follow-up reminders. It never submits or contacts anyone. First live run found a scoring flaw (Immunefi expected value scaled with the headline cap, ranking a $3.5M program first at $84/h); fixed so security bounties are scored as long shots (~$1/h) and a test pins that behaviour.
* `content/` holds the write-up draft (every figure generated from the result files) and a pitch template.
