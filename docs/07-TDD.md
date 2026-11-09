# 07 — TDD: Technical Design Document

*Documento de Diseño Técnico.* Here TDD means the technical design, not test-driven development, although tests are specified in §7.

## 1. Technology

| Concern | Choice | Reason |
|---|---|---|
| Language | Python 3.12+ | Matches v1; low operator cost |
| Types | `pydantic` v2, `mypy --strict` | Bad data fails at the boundary |
| Chain client | `web3.py` plus Foundry `cast` for read diagnostics | Already in use |
| Simulation | Foundry `anvil --fork-url` | Proven by the Dolomite deposit |
| Database | SQLite in WAL mode | [ADR-0009](adr/0009-sqlite-first.md) |
| Scheduling | systemd timers | Survives restarts; replaces agent-driven cron |
| Signing | `eth-account` with an encrypted Foundry-format keystore | Minimal dependencies |
| Telegram | Dedicated bot, separate token from Hermes | Isolation |
| Dashboard | Static site from read models, behind authentication | No server to attack |
| Packaging | `uv` with hash-locked requirements | Reproducible money path |

## 2. Algorithms

### 2.1 Net EV and payback

```
all_in_cost  = gas_in + gas_out + fees + slippage
benefit      = base_yield × notional × horizon/365 + points_ev + rewards_ev
risk_charge  = notional × annual_loss_rate(protocol) × horizon/365
net_ev       = benefit − all_in_cost − risk_charge − opportunity_cost
allow only if net_ev > 0 AND benefit ≥ 3 × all_in_cost
```

`gas` uses live base fee, a simulated gas figure and the L1 data fee. `annual_loss_rate` is a registry setting per protocol, reviewed by the operator; default 2% for blue-chip, higher otherwise.

**Worked example (a $2 vault deposit, using v1's real Morpho deposit).** $2 notional at 4.3% APY over a 365-day horizon gives a benefit of $0.086. Priced correctly, the real transaction cost about $0.05 including the L1 data fee, so entry passes the 3× test. Had v1's log been right that gas was $2.98, the same rule would have rejected it by about 100×. The ledger later showed the log was wrong; the rule is what protects against believing either number blindly, because it uses live gas.

### 2.2 Airdrop EV (replaces hand-typed payouts)

```
p            = min(class_cap(evidence), calibrated_p)
my_share     = my_points / estimated_total_points         # when points are published
pool_usd     = fdv_estimate × airdrop_pct × haircut        # FDV low case; haircut default 0.5
gross_ev     = p × pool_usd × my_share × P(not filtered)
marginal_ev  = gross_ev − gross_ev_without_this_action
```

Where inputs are unknown, the program stays at E0/E1, `marginal_ev` is set to 0, and only actions that cost effectively nothing are allowed. This is an important change: **unknown programs do not get invented dollar values.**

### 2.3 Gas cap

```
base_p50   = median base fee, last 1 hour (from indexed blocks)
max_fee    = min(3 × base_p50 + tip, ABSOLUTE_CAP)
tip        = min(0.001 gwei, p50 observed tip)
```

With v1's conditions the cap would have been about 0.016 gwei, compared with the 8 gwei actually paid.

### 2.4 LP versus benchmark

For each period, per position:

```
lp_value_end  = token amounts at end price + uncollected fees + rewards
hodl_value    = entry token amounts valued at end price
park_value    = entry USD × (1 + base_rate × days/365)
net_lp        = lp_value_end − gas − swap_costs
alpha_hodl    = net_lp − hodl_value
alpha_park    = net_lp − park_value
```

An LP strategy must beat both over 60 days to stay live. `cl-lp-managed` only rebalances when expected fee gain over the horizon exceeds swap cost + gas + realized IL by 2×.

### 2.5 Reconciliation

```
for each managed asset/position at block B (2-RPC agreement):
    delta = ledger_balance(B) − chain_balance(B)
tolerance_usd = max($0.05, 0.25% NAV)
any |delta| beyond tolerance → BREACH → halt, open incident
```

Interest accrual and LP fee growth are booked as accrual events before comparison. Unknown accruals surface as breaches, and are never auto-absorbed.

### 2.6 Performance

Time-weighted return is computed between contribution events, so deposits never count as gains. Reported in USD and against ETH.

### 2.7 Forecast scoring

Brier score over resolved forecasts, by evidence class and strategy. Once a class has at least 20 resolutions, its calibrated probability is lowered if observed frequency is below the stated figure.

## 3. Execution mechanics

- **Nonce:** single-writer executor; nonce from 2-RPC agreement; one in-flight transaction per address in S0.
- **Stuck transactions:** after 10 minutes, replacement only if R-05 still allows it; otherwise alert.
- **Confirmation:** 10 blocks before reconciliation in S0.
- **Idempotency:** `intent_id` is deterministic with a `UNIQUE` constraint in `transactions`.
- **Reorg:** if a confirmed transaction disappears, emit a reversal event and halt.
- **Simulation:** start anvil at the latest safe block, apply calls in order, diff tracked balances and allowances, tear down. One fork per plan.

## 4. Data sources

| Data | Primary | Check |
|---|---|---|
| Wallet state | RPC event logs | Second RPC |
| ETH/USD | Chainlink on Base | Pool TWAP; CEX spot if available |
| Stables | Chainlink | Peg band |
| Protocol info | DeFiLlama | Official docs |
| Incentives | Merkl API | On-chain reward state |
| Programs | Official docs and apps | Human |

v1's dependence on aggregator or affiliate pages ends here. They can raise a candidate but cannot lift evidence above E0.

## 5. Security implementation

1. Three Linux users: `v2app`, `v2signer`, `v2audit`. Hermes keeps running as `latitude`.
2. **`latitude` must have no sudo rights** while keys exist on the machine.
3. Keystore is encrypted at rest. The passphrase is entered at unlock and never stored.
4. Signer unit: `PrivateNetwork=yes`, `NoNewPrivileges=yes`, `ProtectSystem=strict`, `MemoryDenyWriteExecute=yes`.
5. Halt flag lives in `/var/lib/v2/halt/`: writable by core, auditor and surface, readable by signer.
6. CI scans for secrets, forbidden imports and hardcoded business values.
7. Receipt key belongs to `v2app`. A compromised core could forge receipts, which is why the signer keeps independent limits and S1 adds on-chain roles.

## 6. Observability

- JSON logs, `correlation_id = intent_id`.
- Each job writes `job_runs`, which feed SLI queries in [09](09-SLA-SLO-SLI.md).
- Halt-class alerts go to Telegram with a local desktop fallback.
- The dashboard shows a data timestamp on every card.

## 7. Testing

| Layer | Scope | Examples |
|---|---|---|
| Unit | Pure logic | EV math, rule boundaries |
| Property (Hypothesis) | Invariants | Postings always balance; replay is deterministic; no intent survives a failing rule |
| Contract | Schemas | Adapter fixtures, candidate validation |
| Fork | Real protocols on anvil | Supply, withdraw, LP, claim; balance diffs |
| Replay | v1 history | Reconstruct nonces 0–21 and reach the on-chain balance |
| Mutation | Risk and signer | Removing or weakening a rule must fail a test |
| Canary (production) | Live gate | Adversarial plans must be blocked |
| E2E | Whole path on fork | Intent through to reconciliation; every AT in the SRS |

**Canary set:** v1's 8 gwei transaction; unlimited approval; transfer to unknown address; non-allowlisted router; expired receipt; changed implementation; malformed address; duplicate intent; forged receipt; drainer domain; injection payload; stale price. The set grows with every incident.

**CI gates:** tests, 95% money-path branch coverage, `mypy --strict`, import rules, secret scan, no literal values in reported fields.

## 8. Build order

Each step can be demonstrated on its own. Effort is a rough estimate with agent-assisted development.

| # | Work | Estimate |
|---|---|---|
| 1 | Domain types, events, postings, replay | 3 days |
| 2 | Indexer, market data, NAV, reconciler; backfill v1 | 5 days |
| 3 | Dashboard, weekly report; first truthful NAV | 2 days |
| 4 | Registry, code hash checks | 3 days |
| 5 | Simulator, planner, Risk Gate | 6 days |
| 6 | Signer, executor, halt | 4 days |
| 7 | Auditor, canaries | 4 days |
| 8 | `core-hold`, `usdc-park`, `claim-watch`, `position-passive` | 4 days |
| 9 | Sources, quarantine, Hermes integration | 3 days |
| 10 | Forecasts, scorecards, lifecycle | 3 days |

About 37 working days of build, followed by 14 days of shadow. `cl-lp-managed` and others come after cutover, through the gates.
