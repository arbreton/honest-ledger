# 03 — NFR: Non-Functional Requirements

*Requisitos No Funcionales*

Measurable targets for these live in [09](09-SLA-SLO-SLI.md). The priority order decides conflicts: **Safety > Correctness > Cost > Availability > Performance.**

## Safety and security

| ID | Requirement |
|---|---|
| NFR-S1 | No LLM, research agent or dashboard process can read key material, enforced by OS user separation |
| NFR-S2 | External content is treated as hostile and never interpreted as instructions |
| NFR-S3 | Fail closed: if any required input (price, gas, RPC quorum, reconciliation) is missing or stale, no transaction is signed |
| NFR-S4 | Maximum loss from full hot-key compromise is bounded by hot balance: at most $100 in S0, on-chain role limits from S1 |
| NFR-S5 | Secrets never appear in logs, prompts, reports, dashboard data or git |
| NFR-S6 | Every money-affecting decision has a tamper-evident receipt (hash chain) |
| NFR-S7 | Dependencies in the money path are pinned by hash; new ones require human review |
| NFR-S8 | Egress from the signer is denied, except its local socket to the executor |

## Correctness

| ID | Requirement |
|---|---|
| NFR-C1 | Monetary values use integer base units or `Decimal`, never binary floats |
| NFR-C2 | Reported values are derived from source data; hardcoded business values fail CI |
| NFR-C3 | The audit path shares no business logic with the path it checks |
| NFR-C4 | Replaying the event log reproduces the ledger byte-for-byte |
| NFR-C5 | All timestamps are stored in UTC with block number where applicable |

## Cost

| ID | Requirement |
|---|---|
| NFR-K1 | Annualized operating cost (hosting, RPC, LLM, tools) is at most 2% of NAV from S1 |
| NFR-K2 | In S0, added cash operating cost is about $0: free RPC tiers and existing host |
| NFR-K3 | S0 gas budget is 2% of NAV per quarter, enforced automatically |
| NFR-K4 | LLM usage is metered per job, with a daily token budget, and runs only on changed content |

## Availability and resilience

| ID | Requirement |
|---|---|
| NFR-A1 | Downtime must be safe: positions at rest must not require the bot to stay solvent |
| NFR-A2 | Automatic recovery after restart, with catch-up indexing and no missed-transaction replay |
| NFR-A3 | At least 3 independent RPC providers; a value needs 2-provider agreement to be trusted for money decisions |
| NFR-A4 | Encrypted database backup daily, off-host; restore tested quarterly |
| NFR-A5 | The signer stays locked after a reboot until the operator unlocks it; everything else runs read-only |

## Performance

| ID | Requirement |
|---|---|
| NFR-P1 | Halt-class alert within 60 seconds of detection |
| NFR-P2 | End-to-end intent to broadcast under 2 minutes excluding human approval |
| NFR-P3 | Position guard cycle: 15 minutes in S0, 1 minute in S1 |

v2 does not compete on latency. Any strategy that needs sub-second execution is out of scope.

## Maintainability

| ID | Requirement |
|---|---|
| NFR-M1 | A new strategy is a single plugin with no core edits |
| NFR-M2 | Money-path modules have at least 95% branch coverage and property tests |
| NFR-M3 | Everything is in git, with CI required for merge |
| NFR-M4 | S0 stays small: target under 6,000 lines excluding tests |
| NFR-M5 | Any component can be understood by the operator from its doc in under 15 minutes |

## Compliance and ethics

| ID | Requirement |
|---|---|
| NFR-E1 | One real identity per program; no Sybil behaviour; program terms are followed |
| NFR-E2 | Records sufficient for the operator's tax reporting are retained for at least 7 years |
| NFR-E3 | The system never interacts with sanctioned addresses; a screening list is checked by the Risk Gate from S1 |

## Observability

| ID | Requirement |
|---|---|
| NFR-O1 | Structured JSON logs with a `correlation_id` from intent through reconciliation |
| NFR-O2 | Every SLI is computed from stored data and can be recomputed |
| NFR-O3 | Each job records start, end, outcome and cost |
