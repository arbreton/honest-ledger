# 08 — RFC-0001: Rebuild as a Ledger-First Farming System

*Request for Comments*

| | |
|---|---|
| Status | **Open for operator review** |
| Author | Claude, for Ari |
| Date | 2026-11-08 |
| Decides | Whether to replace v1, and how |

## 1. Summary

Replace v1's two-bot scan loop with a small, deterministic, ledger-first system. It has one money path, an independent auditor and capabilities that unlock with capital and proven results. Build in shadow, cut over only after 14 clean days, and retire v1.

## 2. Motivation

The [review](00-current-state-review.md) found that v1's reports cannot be trusted, its gates are not in the money path, and one unguarded transaction cost more in gas ($3.73) than all the yield and fees it earned. Patching would keep its central design flaw, which is a loop built around producing reports rather than around owning and measuring positions.

The goal also needs a straight conversation. [PRD §2](01-PRD.md) shows that $100,000 needs contributions. Architecture cannot substitute for capital.

## 3. Proposal

1. **Ledger first.** Build reconciled truth before anything else, so even v1 benefits in week 2.
2. **One money path** with layered, independent limits.
3. **LLMs research, rules decide.** Hermes moves to a read-only role.
4. **Earn by stage.** S0 is honest and nearly free. S1 and above add earning strategies only through gates.
5. **Measure everything against a benchmark,** and retire what fails.
6. **Treat airdrops as capped options** priced from evidence.

## 4. What changes

| Area | v1 | v2 |
|---|---|---|
| Unit of work | 30-minute run | Intent through a state machine |
| Truth | Logs and hand-updated JSON | Chain-reconciled double entry |
| Discovery | Six hardcoded seeds | Adapters + LLM into quarantine |
| Airdrop value | Typed guesses | Evidence class × share of pool |
| Audit | Same code, always PASS | Separate code; can halt |
| Signing | Agent session with `.env` | Isolated signer checking receipts |
| Gas | Unchecked | Dynamic cap, enforced twice |
| Learning | Fixed lesson strings | Resolved forecasts, benchmarks |
| Risk growth | Manual ambition | NAV stages and strategy gates |

## 5. What stays

Base as the home chain, anvil fork simulation, multi-RPC checks, hard-zero scam rules, paper-first discipline, the existing wallet's history, and Hermes for research and reporting.

## 6. Alternatives considered

| Option | Verdict | Why |
|---|---|---|
| **A. Patch v1** | Rejected | Bolted-on gates remain outside the agent's path; truth problems are structural |
| **B. Ledger-first monolith (this RFC)** | **Chosen** | Smallest design that delivers isolation and truth |
| **C. Microservices with queue** | Rejected | Operating burden and cost with no benefit at this scale |
| **D. Agent-native autonomous swarm** | Rejected | Worsens the core risk: untrusted reasoning near keys |
| **E. No bot: manual and index-style** | Serious alternative | At $65, simply depositing into Morpho and DCA gets most of the return. Justified only if the operator values the system, or capital grows |
| **F. Buy a vault or yield aggregator** | Partial | Used inside `usdc-park`, but leaves measurement and airdrop positioning unsolved |

Option E deserves to be taken seriously: **until NAV is around $1,000, the system's value lies in safety, measurement and readiness to scale. It will not earn its build cost at $65.**

## 7. Drawbacks

- About 37 working days of build before v2 goes live, with no return during that time.
- Stricter gates mean missing some opportunities. This is intended.
- More moving parts than a script, though far fewer than a distributed system.
- S0 key isolation is imperfect on a shared PC.

## 8. Rollout

See [10-migration-plan](10-migration-plan.md). Summary: stabilize v1, build truth in shadow, build the money path on a fork, run 14 days parallel, cut over, retire v1.

## 9. Decisions needed from the operator

| # | Decision | Recommendation |
|---|---|---|
| D1 | Monthly contribution: $0, $250, **$500**, $1,000 | $500 if affordable; only money you can afford to lose |
| D2 | Target date for $100k | Derive from D1; about 8.7 years at $500/mo and 15% |
| D3 | Build v2 now, or use manual approach (Option E) until $1k? | Build P0 (ledger, gate, signer); defer P1/P2 until contributions start |
| D4 | Approve the M0 stabilization of v1 (removes standing authority) | Yes, first |
| D5 | LP at cutover | Exit to Core unless shadow shows it beating hold and park |
| D6 | Risk tolerance: maximum drawdown you can sit through | Needed to finalize bucket sizes |
| D7 | Tax handling | Confirm obligations with a local accountant before S1 |

## 10. Open questions

- Can Telegram approvals share the phone used for other accounts, or should a separate device hold them?
- Which vault is the S0 store for contributions above the hot cap (see [ADR-0008](adr/0008-custody-eoa-then-safe-roles.md))?
- Which paid RPC, if any, at S1?
