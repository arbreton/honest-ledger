# 02 — SRS: Software Requirements Specification

*Especificación de Requisitos de Software*

"MUST" items are required for the listed stage. `Origin` links to review findings in [00](00-current-state-review.md). Non-functional requirements are in [03](03-NFR.md).

## 1. Ledger and reconciliation

| ID | Requirement | Stage | Origin |
|---|---|---|---|
| FR-L1 | MUST record every balance change as balanced double-entry postings derived from an append-only event log | S0 | F-05, F-06 |
| FR-L2 | MUST index all transactions and token transfers for each managed address from chain data | S0 | F-23 |
| FR-L3 | MUST attribute L2 gas plus L1 data fee in native units to a strategy on every transaction | S0 | F-16, F-20 |
| FR-L4 | MUST compute NAV from on-chain balances, position contracts and live prices, in USD and ETH | S0 | F-09 |
| FR-L5 | MUST reconcile ledger against chain on schedule and after each transaction, and raise a halt on breach of tolerance | S0 | F-09 |
| FR-L6 | MUST flag any nonce or transfer without a decision receipt as `UNATTRIBUTED` and halt | S0 | F-23 |
| FR-L7 | MUST record contributions and withdrawals separately, so performance is unaffected by deposits | S0 | F-10 |
| FR-L8 | MUST backfill v1 history from nonce 0 | S0 | §2 |
| FR-L9 | SHOULD export per-lot cost basis and income events for tax use | S1 | — |

## 2. Registry and evidence

| ID | Requirement | Stage | Origin |
|---|---|---|---|
| FR-R1 | MUST store protocols, contracts, tokens and programs as versioned records with attached evidence | S0 | F-04, F-11 |
| FR-R2 | MUST classify evidence from E0 to E4 ([LLD §6](06-LLD.md)); affiliate or aggregator pages cannot exceed E0 | S0 | F-11 |
| FR-R3 | MUST pin each allowlisted contract's address, code hash and, for proxies, implementation address | S0 | F-26 |
| FR-R4 | MUST validate address checksum and length when a record is written | S0 | F-26 |
| FR-R5 | MUST detect a code hash change and halt affected strategies | S0 | — |
| FR-R6 | MUST require human approval to add or change a contract allowlist entry | S0 | F-24 |

## 3. Discovery and research

| ID | Requirement | Stage | Origin |
|---|---|---|---|
| FR-D1 | MUST ingest from real adapters (official docs and APIs, DeFiLlama, Merkl, GitHub, on-chain factories) and record fetch health | S0 | F-04 |
| FR-D2 | MUST run research on a content-change trigger, not on a fixed cycle over unchanged data | S0 | F-33 |
| FR-D3 | LLM research MUST output only schema-validated candidates into quarantine | S0 | F-25 |
| FR-D4 | Candidates MUST NOT become registry entries without deterministic verification and human approval | S0 | F-04 |
| FR-D5 | MUST sanitize external text and scan it for injection before any LLM sees it | S0 | F-29 |

## 4. Strategy and allocation

| ID | Requirement | Stage | Origin |
|---|---|---|---|
| FR-S1 | Strategies MUST be deterministic given a state snapshot, and propose intents only | S0 | F-34 |
| FR-S2 | Every intent MUST carry a net EV computed from live gas, live prices and evidence-derived probabilities | S0 | F-11, F-20 |
| FR-S3 | Allocator MUST enforce bucket targets, stage permissions and protocol concentration limits | S0 | — |
| FR-S4 | MUST refuse intents whose expected benefit over the holding horizon is below 3× all-in cost | S0 | F-16 |
| FR-S5 | Every speculative intent MUST register a forecast with a resolution date | S0 | F-06 |
| FR-S6 | MUST compare each strategy to its benchmark net of gas, fees and IL | S0 | F-21 |
| FR-S7 | Strategy promotion MUST follow gates G0–G5 ([LLD §7](06-LLD.md)) | S0 | — |
| FR-S8 | MUST automatically demote a strategy that hits a kill rule | S0 | §4 |
| FR-S9 | LP strategies MUST read fees, liquidity and gauge status from chain | S1 | F-19, F-21, F-22 |

## 5. Execution and safety

| ID | Requirement | Stage | Origin |
|---|---|---|---|
| FR-X1 | MUST be the only path that can sign for managed addresses | S0 | F-23 |
| FR-X2 | MUST simulate every plan on a fork of the current block and compare balance changes to the plan | S0 | §4 |
| FR-X3 | Risk Gate MUST evaluate all rules ([LLD §5](06-LLD.md)) and persist a decision receipt | S0 | F-24 |
| FR-X4 | MUST reject gas price above the dynamic cap and gas cost above 1% of notional | S0 | F-16 |
| FR-X5 | MUST use exact-amount approvals and revoke any residual allowance | S0 | §3 |
| FR-X6 | Signer MUST verify the Risk Gate's signature, plan hash and expiry before signing | S0 | F-25 |
| FR-X7 | MUST be idempotent: the same intent can never produce two broadcasts | S0 | — |
| FR-X8 | Kill switch MUST block signing within one check cycle, independent of the main app | S0 | F-28 |
| FR-X9 | Bridges, new protocols, and amounts above stage limits MUST require human approval | S0 | — |
| FR-X10 | Bot role MUST be limited on-chain to allowlisted targets and functions | S1 | F-25 |

## 6. Audit, reporting, operations

| ID | Requirement | Stage | Origin |
|---|---|---|---|
| FR-A1 | Auditor MUST run from a separate codebase and recompute NAV and attribution from raw chain data | S0 | F-01–F-03 |
| FR-A2 | Auditor MUST be able to halt but not approve or sign | S0 | F-27 |
| FR-A3 | Auditor MUST run adversarial canary intents through the real Risk Gate daily; any canary that passes halts the system | S0 | F-29 |
| FR-A4 | Dashboard MUST read only from ledger-derived views and show each value's age | S0 | F-09 |
| FR-A5 | Dashboard MUST NOT be public | S0 | F-30 |
| FR-A6 | Telegram MUST provide alerts, approvals and `/halt` from an allowlisted chat | S0 | — |
| FR-A7 | MUST send a weekly report: NAV versus plan, net P&L by strategy, costs, forecast calibration | S0 | F-33 |
| FR-A8 | Code changes MUST go through git with human merge; no self-applying changes in the money path | S0 | F-27, F-32 |

## 7. Stage entry gates

| Into | Gates |
|---|---|
| **S0 live** | P0 complete; 14-day shadow clean; 0 out-of-band transactions; canaries all blocked |
| **S1** | NAV at least $1,000; 60 days S0 with reconciliation SLO met; Safe deployed and recovery tested |
| **S2** | NAV at least $10,000; 180 days of audited history; at least 2 strategies beating benchmark over 90 days; hardware signer; external review of contracts in use |
| **S3** | NAV at least $50,000; 2-of-3 custody; written recovery runbook tested |

## 8. Acceptance tests

| ID | Scenario | Expected |
|---|---|---|
| AT-1 | Manual transaction sent from the wallet | `UNATTRIBUTED`, halt, alert under 15 minutes |
| AT-2 | Plan with 8 gwei fee at 0.005 gwei base | Rejected by rule R-05 |
| AT-3 | $2 deposit with payback over the horizon | Rejected by FR-S4 |
| AT-4 | Plan requests unlimited approval | Rejected, canary logged |
| AT-5 | Contract implementation changes | Strategy halted, alert |
| AT-6 | Kill switch set during signing queue | No signature issued |
| AT-7 | Duplicate intent delivered | One broadcast |
| AT-8 | Dashboard data older than its SLO | Shown as stale |
| AT-9 | Injection text in a fetched page | Quarantined; no registry change |
| AT-10 | Signer receives a plan with a bad receipt | Refused, security alert |
| AT-11 | Ledger drifts from chain beyond tolerance | Halt, incident opened |
| AT-12 | LLM process attempts to read signer key file | Denied by OS permissions |
