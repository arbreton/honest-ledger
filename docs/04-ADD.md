# 04 — ADD: Architecture Design Document

*Documento de Diseño de Arquitectura*

This document explains the architecture's shape and why it has that shape. Components and flows are in the [HLD](05-HLD.md), and exact contracts in the [LLD](06-LLD.md).

## 1. Architectural drivers

| Driver | Consequence |
|---|---|
| Money is irreversible | One narrow, independently enforced path to a signature |
| v1's failure was self-deception | The ledger reconciles to chain; auditing is independent |
| Agents read hostile content | Untrusted reasoning is physically separated from keys |
| $65 today, maybe $100k later | Capabilities unlock by stage; S0 costs about $0 to run |
| One operator | No microservices or distributed systems; low attention |
| Airdrops pay late and uncertainly | Forecasts are stored and resolved, so judgment is measurable |

## 2. Principles

1. **The chain is the truth; the ledger must agree or the system stops.**
2. **One way to move money.** If it did not come through the pipeline, it is an incident.
3. **Rules decide; models read.** LLMs summarize and propose research only.
4. **Net or it did not happen.** Every result is after gas, fees, IL and the benchmark.
5. **Fail closed, be safe at rest.** Downtime must never lose money.
6. **Earn the right to take risk.** Stage and strategy gates are evidence-based.
7. **Independent verification.** A checker that shares code with what it checks is not a checker.
8. **Only build what the current stage needs.**

## 3. Style

A **modular monolith with three isolation boundaries**, event-sourced at the ledger.

| Boundary | Separates | Enforced by |
|---|---|---|
| **Signing** | Keys from everything else | OS user, Unix socket, independent limit checks; on-chain roles from S1 |
| **Audit** | Verifier from verified | Separate code, OS user, RPC path; read-only access to core data |
| **Trust** | Untrusted content and LLMs from decisions | Quarantine inbox; schema validation; deterministic verification |

Alternatives are in [RFC-0001 §6](08-RFC-0001-v2-architecture.md).

## 4. Logical view

```
 UNTRUSTED ZONE       │ DECISION ZONE (deterministic)                  │ KEY ZONE
                      │                                                 │
 Web, docs, feeds     │  Registry ─► Strategies ─► Allocator            │
       │              │     ▲              ▲            │               │
       ▼              │     │              │            ▼               │
 Research agent ──────┼─► Quarantine    State ◄─ Ledger  Risk Gate      │
 (Hermes / LLM)       │   + verifier       ▲       ▲        │           │
                      │                    │       │        ▼           │
                      │                 Indexer ◄──┘    Executor ───────┼─► Signer
                      │                    ▲                 │          │   (limits)
 ─────────────────────┼────────────────────┼─────────────────┼──────────┼───────
                      │                    └──── Base chain ◄┘          │
 AUDIT ZONE: Auditor (separate code, own RPC) reads chain + core DB; can only HALT
```

## 5. Key design decisions

| Topic | Decision | ADR |
|---|---|---|
| Shape | Modular monolith + isolated signer and auditor | [0001](adr/0001-modular-monolith-with-isolated-signer.md) |
| State | Event-sourced double-entry ledger | [0002](adr/0002-event-sourced-double-entry-ledger.md) |
| LLM role | Outside the money path | [0003](adr/0003-llms-outside-the-money-path.md) |
| Authorization | Single pipeline with signed receipts | [0004](adr/0004-single-money-path-signed-receipts.md) |
| Pre-trade | Mandatory fork simulation | [0005](adr/0005-mandatory-fork-simulation.md) |
| Risk growth | NAV-based stages | [0006](adr/0006-capital-stage-gating.md) |
| Identity | One identity, no Sybil | [0007](adr/0007-one-identity-no-sybil.md) |
| Custody | Capped EOA, then Safe with Roles | [0008](adr/0008-custody-eoa-then-safe-roles.md) |
| Storage | SQLite, with a trigger for Postgres | [0009](adr/0009-sqlite-first.md) |
| Chains | Base only until S2 | [0010](adr/0010-base-only-until-s2.md) |
| Airdrop valuation | Evidence classes and share-of-pool model | [0011](adr/0011-evidence-based-airdrop-ev.md) |
| Hermes | Read-only research and reporting | [0012](adr/0012-hermes-readonly-role.md) |
| Audit | Shared-nothing auditor with halt-only power | [0013](adr/0013-independent-auditor.md) |
| Hosting | Existing PC, VPS from $3k | [0014](adr/0014-hosting-by-stage.md) |

## 6. Quality attribute tactics

| Attribute | Tactics |
|---|---|
| Safety | Layered limits (Risk Gate, Signer, on-chain role), kill switch, exact approvals, pinned code hashes |
| Correctness | Event replay, double entry, reconciliation, integer math, property tests |
| Cost | Gas gate, payback test, change-triggered research, free tiers in S0 |
| Availability | Stateless restart, catch-up indexing, RPC quorum, safe-at-rest positions |
| Evolvability | Strategy, source and rule plugins with stable contracts |
| Auditability | Hash-chained receipts, correlation IDs, replayable state |

## 7. Threat model

| Threat | Vector | Controls | Residual |
|---|---|---|---|
| Prompt injection moves funds | Malicious docs or feeds | LLM has no path to Risk Gate or Signer | Bad candidates, blocked by verification and human |
| Drainer contract | Fake campaign, poisoned address | Allowlist, code hash, simulated balance diffs, human for new contracts | Protocol itself turns malicious |
| Unlimited approval abuse | Router compromise | Exact-amount, revoke after use | One transaction's exposure |
| Compromised core app | Bug or dependency | Signer re-checks limits; on-chain roles from S1 | Losses up to daily cap until halt |
| Key theft | Host compromise | Encrypted keystore, separate user, low hot balance | In S0, up to hot balance; shared host is a real limit |
| Gas overpay | Bad parameter | Gas rule in both Risk Gate and Signer | None material |
| Oracle or price spoof | Bad data | Multi-source price, staleness and deviation limits | Short windows |
| Reorg | L2 reorg | Confirmation depth before reconciliation | Rare, detected on replay |
| Phishing claim | Fake airdrop site | Claim only via registry contracts, E3+ evidence | Human error when approving |
| Self-modifying agent | Auto-applied code | Human-merged git only | None material |
| Operator error | Wrong approval | Clear approval text, stage limits, cool-off for large amounts | Inherent |

**Honest limit of S0.** The signer shares a machine with the agent. OS separation only helps if the agent's account has no `sudo` and the Windows host is trusted. That is why S0 caps hot funds at $100.

## 8. Deployment by stage

| | S0 | S1 from $3k | S2/S3 |
|---|---|---|---|
| Host | Existing PC, WSL | Small VPS | VPS, warm standby |
| Custody | Legacy EOA, capped | Safe; bot key with Roles | Hardware or 2-of-3 owners |
| Database | SQLite WAL | SQLite WAL | Postgres when triggered |
| RPC | Free, 3 providers | Paid primary, free backup | Paid, 2 providers |
| Backup | Encrypted, off-host, daily | Same | Same, plus restore drill |

## 9. Constraints and assumptions

- The operator runs the system alone and approves from Telegram.
- Blue-chip protocols keep operating; concentration limits contain the case where they do not.
- Free RPC tiers remain usable at S0 volumes.
- Airdrop rules are unknown in advance, so the design never depends on them.
