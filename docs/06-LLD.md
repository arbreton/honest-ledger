# 06 — LLD: Low-Level Design

*Diseño de Bajo Nivel*

## 1. Repository layout

```
crypto-scanner-v2/
  apps/
    core/          # scheduler, jobs, composition root
    signer/        # standalone, no imports from core (under 300 lines)
    auditor/       # standalone, no imports from core
    surface/       # Telegram, report, dashboard generator
  packages/
    domain/        # types, money, IDs (no I/O)
    ledger/        # events, postings, NAV, reconcile
    registry/      # protocols, contracts, programs, evidence
    sources/       # adapters
    research/      # quarantine, verifier
    market/        # price and gas
    strategies/    # one module per strategy
    allocator/
    planner/       # calldata from registry ABIs
    simulator/     # anvil fork control, diffs
    risk/          # one module per rule
    execution/     # nonce, broadcast, confirm
    forecasts/
  registry-data/   # reviewed YAML: contracts, programs
  migrations/
  tests/{unit,property,fork,e2e,canaries}
  ops/             # systemd units, install, backup, runbooks
  docs/
```

**Import rules, enforced in CI:** `signer` and `auditor` import nothing from `packages/`. `strategies` import only `domain`. Only `execution` calls the signer socket.

## 2. Core types

```python
class Intent(BaseModel, frozen=True):
    intent_id: str                  # sha256(strategy, action, params, window)
    strategy: StrategyId
    bucket: Literal["core", "farm", "options"]
    action: ActionType              # SUPPLY, WITHDRAW, SWAP, LP_ADD, LP_REMOVE, CLAIM, REVOKE...
    protocol: str                   # registry ID, never an address
    params: dict[str, Decimal | str]
    notional_usd: Decimal
    ev: EVBreakdown
    horizon_days: int
    expires_at: datetime
    forecast_id: str | None

class EVBreakdown(BaseModel, frozen=True):
    gross_benefit_usd: Decimal
    gas_usd: Decimal
    fees_usd: Decimal
    slippage_usd: Decimal
    risk_charge_usd: Decimal
    opportunity_cost_usd: Decimal
    evidence_class: Literal["E0", "E1", "E2", "E3", "E4"] | None
    inputs_hash: str

class Plan(BaseModel, frozen=True):
    plan_id: str
    intent_id: str
    calls: tuple[Call, ...]         # target, selector, calldata, value
    expected_diffs: tuple[BalanceDiff, ...]
    max_fee_per_gas: int
    gas_limit: int

class DecisionReceipt(BaseModel, frozen=True):
    receipt_id: str
    plan_hash: str
    decision: Literal["ALLOW", "REJECT", "NEEDS_HUMAN"]
    rules: tuple[RuleResult, ...]
    approval_ref: str | None
    block_simulated: int
    expires_at: datetime
    prev_receipt_hash: str
    sig: str                        # HMAC for S0, Ed25519 from S1
```

Plugin contracts:

```python
class Strategy(Protocol):
    id: StrategyId
    min_stage: Stage
    def propose(self, s: StateSnapshot) -> list[Intent]: ...
    def benchmark(self, s: StateSnapshot, since: datetime) -> Decimal: ...

class RiskRule(Protocol):
    id: str
    severity: Literal["BLOCK", "HUMAN"]
    def check(self, p: Plan, sim: SimResult, s: StateSnapshot) -> RuleResult: ...

class SourceAdapter(Protocol):
    id: str
    def fetch(self, since: datetime) -> Iterable[RawDocument]: ...
```

## 3. Database schema (SQLite, STRICT tables, `foreign_keys=ON`)

Amounts are stored as `TEXT` integer base units.

```sql
-- Ledger
CREATE TABLE events (
  seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, type TEXT NOT NULL,
  chain_id INTEGER, block_number INTEGER, tx_hash TEXT, log_index INTEGER,
  payload TEXT NOT NULL, occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL,
  UNIQUE (chain_id, tx_hash, log_index, type)
) STRICT;

CREATE TABLE accounts (
  account_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('asset','liability','equity','income','expense')),
  name TEXT NOT NULL, protocol_id TEXT, address TEXT
) STRICT;

CREATE TABLE journal (
  journal_id TEXT PRIMARY KEY, event_seq INTEGER NOT NULL REFERENCES events(seq),
  strategy TEXT, correlation_id TEXT, memo TEXT
) STRICT;

CREATE TABLE postings (
  posting_id INTEGER PRIMARY KEY, journal_id TEXT NOT NULL REFERENCES journal(journal_id),
  account_id TEXT NOT NULL REFERENCES accounts(account_id), asset_id TEXT NOT NULL,
  amount TEXT NOT NULL, usd_value TEXT NOT NULL
) STRICT;  -- Invariant: within each journal the amounts of EACH ASSET sum to zero (enforced in code, tested). usd_value is informational (positions such as LP NFTs and vault shares are valued at NAV time, not at posting time)

CREATE TABLE nav_snapshots (
  ts TEXT PRIMARY KEY, block_number INTEGER NOT NULL, nav_usd TEXT NOT NULL, nav_eth TEXT NOT NULL,
  net_contributions_usd TEXT NOT NULL, breakdown TEXT NOT NULL, price_source TEXT NOT NULL
) STRICT;

CREATE TABLE reconciliations (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, block_number INTEGER NOT NULL,
  ledger_usd TEXT NOT NULL, chain_usd TEXT NOT NULL, delta_usd TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('OK','BREACH')), detail TEXT NOT NULL
) STRICT;

-- Registry
CREATE TABLE protocols (
  protocol_id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
  max_nav_pct REAL NOT NULL, notes TEXT
) STRICT;

CREATE TABLE contracts (
  chain_id INTEGER NOT NULL, address TEXT NOT NULL, protocol_id TEXT NOT NULL REFERENCES protocols(protocol_id),
  role TEXT NOT NULL, code_hash TEXT NOT NULL, impl_address TEXT, impl_code_hash TEXT,
  allowed_selectors TEXT NOT NULL, status TEXT NOT NULL,
  approved_by TEXT NOT NULL, approved_at TEXT NOT NULL,
  PRIMARY KEY (chain_id, address)
) STRICT;

CREATE TABLE programs (
  program_id TEXT PRIMARY KEY, protocol_id TEXT, name TEXT NOT NULL, kind TEXT NOT NULL,
  evidence_class TEXT NOT NULL, season_end TEXT, status TEXT NOT NULL, terms_url TEXT
) STRICT;

CREATE TABLE evidence (
  evidence_id TEXT PRIMARY KEY, program_id TEXT REFERENCES programs(program_id),
  protocol_id TEXT, url TEXT NOT NULL, source_kind TEXT NOT NULL, content_hash TEXT NOT NULL,
  quote TEXT NOT NULL, fetched_at TEXT NOT NULL, class TEXT NOT NULL
) STRICT;

CREATE TABLE candidates (
  candidate_id TEXT PRIMARY KEY, source TEXT NOT NULL, payload TEXT NOT NULL,
  status TEXT NOT NULL, rejection TEXT, created_at TEXT NOT NULL
) STRICT;

-- Money path
CREATE TABLE intents (
  intent_id TEXT PRIMARY KEY, strategy TEXT NOT NULL, payload TEXT NOT NULL,
  state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE plans (
  plan_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL REFERENCES intents(intent_id),
  payload TEXT NOT NULL, plan_hash TEXT NOT NULL
) STRICT;

CREATE TABLE simulations (
  sim_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id),
  block_number INTEGER NOT NULL, success INTEGER NOT NULL, gas_used INTEGER NOT NULL,
  diffs TEXT NOT NULL, trace_hash TEXT NOT NULL
) STRICT;

CREATE TABLE decision_receipts (
  receipt_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(plan_id),
  decision TEXT NOT NULL, rules TEXT NOT NULL, approval_ref TEXT,
  expires_at TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL, sig TEXT NOT NULL
) STRICT;

CREATE TABLE transactions (
  tx_hash TEXT PRIMARY KEY, intent_id TEXT NOT NULL UNIQUE REFERENCES intents(intent_id),
  receipt_id TEXT NOT NULL REFERENCES decision_receipts(receipt_id),
  nonce INTEGER NOT NULL, from_address TEXT NOT NULL, status TEXT NOT NULL,
  gas_used INTEGER, effective_gas_price TEXT, l1_fee TEXT, block_number INTEGER
) STRICT;

-- Declared human actions (deposits, emergency moves)
CREATE TABLE declarations (
  id INTEGER PRIMARY KEY, tx_hash TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
  note TEXT NOT NULL, declared_at TEXT NOT NULL
) STRICT;

-- Learning
CREATE TABLE forecasts (
  forecast_id TEXT PRIMARY KEY, strategy TEXT NOT NULL, question TEXT NOT NULL,
  probability REAL NOT NULL, value_usd TEXT, evidence_class TEXT NOT NULL,
  resolve_by TEXT NOT NULL, created_at TEXT NOT NULL,
  outcome INTEGER, realized_usd TEXT, resolved_at TEXT
) STRICT;

CREATE TABLE strategy_state (
  strategy TEXT PRIMARY KEY, gate TEXT NOT NULL, cap_usd TEXT NOT NULL,
  paused_reason TEXT, updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE incidents (
  incident_id TEXT PRIMARY KEY, severity TEXT NOT NULL, kind TEXT NOT NULL,
  detail TEXT NOT NULL, opened_at TEXT NOT NULL, closed_at TEXT, postmortem TEXT
) STRICT;

CREATE TABLE job_runs (
  id INTEGER PRIMARY KEY, job TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
  outcome TEXT, cost_usd TEXT, detail TEXT
) STRICT;
```

The events table has triggers that reject `UPDATE` and `DELETE`. The Auditor has its own database with `attestations` and `canary_results`.

## 4. State machines

**Intent**

```
PROPOSED → BUDGETED → PLANNED → SIMULATED → ALLOWED ───────► SIGNED → BROADCAST → CONFIRMED → RECONCILED
                                     │          ▲                              │
                                     ▼          │                              ▼
                                  REJECTED   NEEDS_HUMAN → (approve)         FAILED
Any state before SIGNED → EXPIRED
```

Rules: transitions are recorded as events. A `FAILED` intent is never retried automatically under the same ID; the strategy must propose again from fresh state.

**Global mode:** `RUNNING → HALTED → RUNNING (operator only)`. Any component may halt; only the operator may resume, and resuming needs a green reconciliation.

## 5. Risk rules

BLOCK rejects. HUMAN escalates. Limits are for S0 unless stated.

| ID | Sev | Rule |
|---|---|---|
| R-01 | BLOCK | Global halt is not set |
| R-02 | BLOCK | Latest reconciliation OK and under 30 min old |
| R-03 | BLOCK | Each target and selector is allowlisted and active |
| R-04 | BLOCK | Live code hash matches the pinned value |
| R-05 | BLOCK | `maxFee ≤ min(3 × p50 base fee over 1h + tip, 0.05 gwei)` (absolute cap reviewed per chain) |
| R-06 | BLOCK | Gas cost ≤ 1% of notional, and within remaining quarterly gas budget |
| R-07 | BLOCK | Net EV > 0 and benefit over horizon ≥ 3 × all-in cost |
| R-08 | BLOCK | Simulation succeeded; balance diffs within tolerance of plan |
| R-09 | BLOCK | No value leaves to any non-managed address, except allowlisted protocol contracts |
| R-10 | BLOCK | Approvals are exact-amount; none `MAX`; allowance returns to zero after use |
| R-11 | BLOCK | Per-tx ≤ min($25, 25% NAV) |
| R-12 | BLOCK | Daily outflow to protocols ≤ min($50, 50% NAV) |
| R-13 | BLOCK | Stage, gate and bucket permit this strategy and notional |
| R-14 | BLOCK | Protocol concentration within `max_nav_pct` after the action |
| R-15 | BLOCK | Price fresh (≤ 5 min), sources within 1% |
| R-16 | BLOCK | At least 2 RPCs agree on nonce and balance |
| R-17 | BLOCK | Farm + Options drawdown under 10% daily and 20% weekly (Core market moves do not trigger this rule) |
| R-18 | BLOCK | Receipt and plan not expired; simulated block within 20 blocks |
| R-19 | BLOCK | Evidence class meets action minimum (claim: E3 or higher) |
| R-20 | HUMAN | New protocol, first use of a selector, or bridge |
| R-21 | HUMAN | Notional above auto-approve limit ($5 in S0) |
| R-22 | HUMAN | Any exit that realizes more than 5% of NAV loss |

**Signer hard limits**, implemented separately in `apps/signer`: halt file; receipt signature, hash and expiry; target in its own static allowlist; per-tx and daily caps; gas price cap; chain ID; no contract creation.

## 6. Evidence classes

| Class | Meaning | Allowed sources | Max probability |
|---|---|---|---:|
| **E0** | Rumour | Aggregators, blogs, social | 0.05 |
| **E1** | Team says it is exploring | Official statement, no program | 0.15 |
| **E2** | Official points or season program, no token terms | Official docs or app | 0.50 |
| **E3** | Token and allocation published | Official announcement plus contract | 0.90 |
| **E4** | Claim live, wallet eligible on-chain | Merkle proof or contract read | 0.99 |

Each class caps the probability; calibration can lower it but cannot raise it above the class cap.

## 7. Strategy lifecycle gates

| Gate | Name | Exit criteria | Cap | Who |
|---|---|---|---|---|
| G0 | Registered | Thesis, benchmark, kill rule written | None | Human |
| G1 | Verified | Contracts pinned, evidence attached | None | Human |
| G2 | Simulated | Fork tests pass; backtest where possible | None | CI |
| G3 | Paper | At least 14 days and 30 observations; net beats benchmark after simulated costs | None | Auto |
| G4 | Canary | Live ≤ min($5, 5% NAV), 14 days; reconciled; no incidents | Small | Human |
| G5 | Live | Cap grows at most 2× per 30 days while beating benchmark | Bucket limit | Human |
| Retired | | Any kill rule | Zero | Auto |

**Default kill rules:** net below benchmark over 60 days; drawdown beyond the strategy's limit; 3 consecutive losing periods; any strategy-caused incident.

## 8. Signer interface

Unix socket, owner `v2signer`, group `v2exec`, mode `0660`.

```jsonc
// Request
{"v":1,"unsigned_tx":{"chain_id":8453,"nonce":22,"to":"0x…","data":"0x…","value":"0",
 "gas":250000,"max_fee_per_gas":"12000000","max_priority_fee_per_gas":"1000000"},
 "receipt":{"receipt_id":"…","plan_hash":"…","expires_at":"…","sig":"…"}}
// Response
{"ok":true,"raw_tx":"0x…"}
{"ok":false,"code":"HALTED|BAD_RECEIPT|EXPIRED|LIMIT|LOCKED|NOT_ALLOWLISTED"}
```

The signer keeps its own append-only daily-spend file. It has no network egress.

## 9. Telegram commands

`/status`, `/nav`, `/halt [reason]`, `/resume` (needs confirmation code), `/approve <id> <code>`, `/deny <id>`, `/declare <tx> <kind> <note>`. Chat ID is allowlisted. Approvals are single-use and expire in 24 hours or less.
