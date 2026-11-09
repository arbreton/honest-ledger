# 12 — Forward paper-trading plan (pre-registered 2026-11-09, before any forward result exists)

Fifteen paper accounts started on 2026-11-09 (02:00 and 03:00 UTC cohorts). Only bars AFTER registration count. Strategies are frozen: parameters cannot change.
Costs, funding and liquidation follow the backtest model. Nothing here touches real money.

## What each stage can honestly tell us
With N daily observations the standard error of an annualised Sharpe ratio is about sqrt(365/N):

| Stage | Date (first cohort) | Daily obs | Annualised Sharpe needed to beat luck (95%) | What the stage is FOR |
|---|---|---|---|---|
| Day 30 | 2026-12-09 | ~30 | ~5.8 | **Sanity screen only**: is anything broken? |
| Day 90 | 2027-02-07 | ~90 | ~3.3 | First performance look; drop clear losers |
| Day 180 | 2027-05-08 | ~180 | ~2.3 | Earliest point a tiny live canary can even be discussed |

So a good day-30 number proves nothing, and a bad one mostly proves nothing either. With 15 accounts, one or two will look great by chance alone.

## Day-30 rules (decided now)
* **LIQUIDATED**: dropped permanently (applies to the 3x perp account if it happens; that is the point of including it).
* **BROKEN**: dropped if the account's live turnover differs from its backtest by more than 3x, or there are data gaps that change signals.
* **CLEARLY LAGGING**: dropped if it trails "hold ETH" by more than 15 percentage points AND has a deeper maximum drop than hold.
* Everything else: **CONTINUE**. No strategy is promoted at day 30, however well it did.

## Day-90 rules
A strategy becomes a *candidate* only if ALL hold: return >= hold ETH; maximum drop <= 75% of hold's; no liquidation; and at least 90 daily observations.

## Day-180 rules (required before any live money)
* Still a candidate at day 90 AND day 180 (a single good check does not count).
* The 180 days must contain both an ETH rise of >= 20% and a fall of >= 20% from a local extreme; otherwise the test is extended until they have.
* Allowed live form: **spot long/flat only, a capped canary of at most $5**, signer allowlist approved by the operator. Perps and leverage have no venue integration and stay paper-only.
* Because 15 accounts were tried, a candidate must also beat the median of the other candidates in its own family; one lucky account is not enough.

## Automatic output
When the first cohort reaches 30 days the system writes `docs/reviews/paper-day30-<date>.md` using exactly these rules, adds a note to `data/outbox.log`, and shows "review ready" on the dashboard.
Nobody has to remember to run anything.
