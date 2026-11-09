# 10 — Migration Plan: v1 to v2

v1 keeps running until cutover. **Every step that touches v1 or moves funds needs explicit operator approval, and nothing in this plan has been executed.** Durations are estimates.

## Overview

| Phase | Goal | Touches v1? | Moves funds? | Duration |
|---|---|---|---|---|
| M0 | Stabilize v1 | Yes, by approval | No | 1 day |
| M1 | Truth in shadow | Reads only | No | 2 weeks |
| M2 | Registry and sources | No | No | 1 week |
| M3 | Money path on fork | No | No | 3 weeks |
| M4 | Parallel shadow | Reads only | No | 14 days |
| M5 | Cutover | Yes | Small canaries | 1 day |
| M6 | Decommission | Yes | No | After 30 days |

## M0. Stabilize v1

| Step | Action | Why |
|---|---|---|
| 0.1 | Edit the `hunter-auditor-2h-60turns` cron prompt on Hermes profile `bot2`: remove standing authority to act and apply code. Keep it read-only, or pause it | F-23, F-25, F-27 |
| 0.2 | Freeze v1 live transactions by operator policy | F-16 |
| 0.3 | Put v1 under git with `.env`, databases and logs excluded | F-32 |
| 0.4 | Check that dashboard data is not publicly exposed, or stop the Netlify deploy | F-30 |
| 0.5 | Run `sudo -n true` as `latitude` and remove passwordless sudo before keys are separated | S0 isolation |
| 0.6 | Confirm whether any deposits or withdrawals happened since Oct 27 | Baseline for P&L |
| 0.7 | Choose a contribution plan (RFC D1) | Sets the whole trajectory |

## M1. Truth in shadow

Build steps 1–3 of the [TDD](07-TDD.md). The wallet is observed, not touched.

Exit criteria:
- Backfill reproduces nonces 0–21 and matches on-chain balances within tolerance.
- 7 days of reconciliation meeting ST-1.
- v2 NAV replaces v1's dashboard numbers.

This phase alone corrects the most misleading part of v1.

## M2. Registry and sources

| v1 source | v2 destination |
|---|---|
| `TINY_LIVE_CHECKLIST.md` addresses | `registry-data/`, each re-verified on Basescan, checksummed and code-hashed |
| `dolomite-next.md`, Morpho vault, NPM | Registry with operator approval |
| `airdrop_programs.py` | `programs` re-graded: Base token at most E1 today |
| `trustworthy-sources.md` | Source adapters and domain policy |
| `resources/what-works.md`, lessons | `docs/lessons.md` and new canaries |

Exit: each program and contract has evidence, and hand-typed `payout_est` values are gone.

## M3. Money path on fork

Build steps 5–7, with signer running a **throwaway test key on anvil only**.

Exit: all SRS acceptance tests pass, the canary set is 100% blocked, and mutation testing covers Risk Gate and Signer.

## M4. Parallel shadow (14 days)

v2 runs end to end, producing intents, plans, simulations and receipts, but the signer is disabled. Each intent is reviewed in the weekly report.

Exit:
- No Sev-1, and SLOs met for the full 14 days.
- Paper results reconciled against what actually happened on-chain.
- Operator reviews a sample of receipts and agrees with them.

## M5. Cutover

**Pre-flight**
- [ ] M4 exit met
- [ ] v1 cron disabled and confirmed not firing
- [ ] Keystore moved to `v2signer`; `.env` copy removed from v1
- [ ] Halt tested end to end
- [ ] Operator has written recovery steps

**Sequence**
1. Halt v2. Disable v1 schedule.
2. Run a final reconciliation and record it as the opening balance.
3. Unlock signer; resume in S0 with auto-approval off.
4. Run canary transaction: wrap or unwrap about $1 through the full path.
5. Reconcile. If OK, run the second canary: USDC parking for about $1.
6. Enable auto-approval for up to $5 after 7 clean days.

**Position disposition**

| Holding | USD | Plan |
|---|---:|---|
| ETH | 27.96 | Core; keep about $3 as gas reserve |
| WETH | 1.36 | Unwrap into Core |
| USDC | 2.03 | Add to `usdc-park` |
| Morpho | 2.00 | Keep; becomes `usdc-park` |
| Dolomite | 1.81 | Keep as an Options position; review in 90 days |
| Slipstream LP | 29.99 | Operator decision RFC D5 |

The LP is not urgent. Its range is roughly $2,063–$2,636 with ETH at $2,127. If ETH falls below the range, the position becomes all WETH and stops earning, but it is still roughly equivalent to holding ETH. Its gauge is dead, so it earns only trading fees.

**Rollback:** set halt. v1 stays disabled for live actions. v2 read paths keep running, so ledger truth is not lost. Fix forward; do not return funds control to v1's agent flow.

## M6. Decommission

After 30 days at SLO:
- Archive `ledger.db`, logs and reports read-only, encrypted and off-host.
- Remove the Hermes cron for v1.
- Remove v1's Netlify deploy.
- Delete the v1 `.env` after confirming nothing references it, with operator sign-off.

## Data mapping

| v1 | v2 |
|---|---|
| Chain history | Rebuilt from chain by the indexer |
| `opportunities`, `audits`, `proposals`, `turns`, `growth_outcomes` | Archived; **not imported**, because the values are unreliable |
| `paper-book.json` | Summary in lessons |
| `lessons` table | `docs/lessons.md` |
| `outcomes` | Empty; nothing to import |

## Wallet and capital plan

Stay with the existing EOA for continuity of on-chain history, and accept that its key has been exposed to the agent's account ([ADR-0008](adr/0008-custody-eoa-then-safe-roles.md)).

- S0 hot balance stays at or below $100.
- Contributions above that go to an operator-held vault wallet that the bot does not control. It appears in NAV as watch-only.
- At S1, a new Safe with fresh owner keys receives Farm capital. The old EOA stays capped as a legacy identity.

## Timeline

| Week | Phase |
|---|---|
| 1 | M0, begin M1 |
| 2–3 | M1 complete |
| 3–4 | M2 |
| 4–7 | M3 |
| 8–9 | M4 |
| 10 | M5 |
| 14+ | M6 |

The dependency that matters most is D1. Without contributions, v2 protects and measures about $65, which is not enough to justify building beyond P0.
