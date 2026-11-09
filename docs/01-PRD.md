# 01 — PRD: Product Requirements Document

*Documento de Requisitos de Producto*

Status: Draft for operator review · Replaces the PRD in `2026-10-26_222357-crypto-scanner-auditor.md`

## 1. Problem

The operator wants to grow a small crypto stack to **$100,000** by farming airdrops and DeFi yield. v1 cannot do this: it does not discover, measure or control anything that matters ([review](00-current-state-review.md)). The bigger issue is that the goal has no viable path at the current capital, whatever software runs it.

## 2. The math of the goal

Starting NAV is $66.53 (ledger-derived, 2026-11-08; the scenario table below used a $65 start, which changes the results by under a month). Reaching $100,000 is **about 1,500×**, or 10.6 doublings.

**Compounding alone does not get there.** Doubling the whole portfolio in a year earns about $65. The required return with no new money is 334% a year for 5 years, or 108% a year for 10 years.

Years to $100,000, starting at $65, by monthly contribution and net annual return:

| Net APY | $0/mo | $100/mo | $250/mo | $500/mo | $1,000/mo | $2,000/mo |
|---:|---:|---:|---:|---:|---:|---:|
| 5% | 100+ | 33.2 | 19.8 | 12.2 | 7.0 | 3.8 |
| 10% | 77.0 | 23.0 | 15.1 | 10.0 | 6.2 | 3.6 |
| 15% | 52.5 | 18.2 | 12.4 | 8.7 | 5.6 | 3.3 |
| 25% | 32.9 | 13.3 | 9.6 | 7.0 | 4.8 | 3.0 |
| 40% | 21.8 | 10.0 | 7.5 | 5.7 | 4.0 | 2.7 |

These are arithmetic, not forecasts. The vault v1 holds (Gauntlet USDC Prime on Morpho) paid about 5–6% a year by on-chain share price over 1–14 days of real time (measured 2026-11-08), in line with the 5.0% DeFiLlama advertises. Even so, advertised yields are claims to verify on-chain. Anything above that carries real risk, and sustaining 25%+ is unproven.

**Three levers exist:**

1. **Contributions** are the only lever the operator fully controls, and at this size they dominate.
2. **Net return** matters more as capital grows, and it is what v2's engine is built to earn and prove.
3. **Windfalls** from airdrops can be large and are real, but cannot be planned. v2 buys these as cheap, capped options and never counts them in the plan.

**Airdrops mostly scale with capital and time.** Published allocations are often roughly linear in points. A $65 wallet gets a small share. That is why v2 keeps positioning cheap now and earns real size later.

**No architecture makes $100k from $65 likely.** v2 is designed so that every dollar added earns a measured return, nothing is lost to avoidable mistakes, and the system takes more risk only after earning that right.

## 3. Vision

A small, honest, self-custodied farming system that knows exactly what it owns, what every action cost and what it earned, and which moves money only through one verifiable path.

## 4. Goals

| ID | Goal | Measure |
|---|---|---|
| G1 | Never lose funds to the system's own failure | 0 drains, 0 unattributed transactions |
| G2 | Tell the truth | Ledger matches chain within tolerance; every figure is derived |
| G3 | Earn more than the benchmark | Net return beats the sleeve's benchmark over 90 days |
| G4 | Hold cheap airdrop options | Positioned in programs that pass the evidence bar, within budget |
| G5 | Reach $100,000 NAV | Tracked against the plan selected in §8 |
| G6 | Stay cheap | Operating cost at most 2% of NAV annualized from S1 |
| G7 | Need little attention | Under 30 minutes a week in normal operation |

## 5. Non-goals

- Sybil farming or multi-wallet identity splitting ([ADR-0007](adr/0007-one-identity-no-sybil.md)).
- Memecoin sniping, MEV, flash loans, leverage in Seed and Build stages.
- Using LLMs to decide, approve or sign.
- Quest grinding, unless a measured hourly rate justifies it.
- A multi-tenant product or managing anyone else's money.
- Guaranteeing any return.

## 6. Users

| Role | Needs |
|---|---|
| **Operator** (Ari) | Weekly truth report, approvals on phone, one-tap kill switch |
| **Strategies** (deterministic code) | Trusted state; a way to propose intents |
| **Research agent** (Hermes/LLM) | Read-only data; a quarantine to submit candidates |
| **Independent auditor** (separate code) | Read-only access to raw chain data and all receipts |

## 7. Capital stages

Stages are defined by NAV. A stage unlocks capabilities only after its entry gates pass (see [SRS §7](02-SRS.md)). Falling below the entry NAV by 20% or more drops one stage.

| Stage | NAV | Allowed | Custody | Host |
|---|---|---|---|---|
| **S0 Seed** | Under $1k | Core ETH, USDC parking, zero-marginal-cost positioning, paper for all else | Existing EOA, capped | Existing PC |
| **S1 Build** | $1k–$10k | Adds concentrated LP, incentive harvesting, capital-weighted points | Safe with scoped bot role | VPS from $3k |
| **S2 Scale** | $10k–$50k | Adds PT/YT, a second chain, carry, if each proves itself | Safe, hardware signer | VPS |
| **S3 Preserve** | $50k and above | Risk sleeves shrink; profits sweep to vault | Safe, 2-of-3 | VPS plus standby |

### Capital buckets

| Bucket | Target S0/S1 | Target S2/S3 | Purpose | Benchmark |
|---|---:|---:|---|---|
| **Core** | 70% / 50% | 50% / 70% | ETH, USDC; low-risk lending | Buy-and-hold / base USDC rate |
| **Farm** | 25% / 40% | 40% / 25% | Proven yield and points | Core return |
| **Options** | 5% / 10% | 10% / 5% | Speculative airdrop positioning | Budget burn |

**Windfall rule:** any realized gain over 5% of NAV sends at least 50% to Core, or to the vault in S3.

## 8. Plan selection

| Plan | Contribution | Assumed net | About |
|---|---|---|---|
| Patient | $250/mo | 15% | 12.4 years |
| **Recommended** | $500/mo | 15% | 8.7 years |
| Aggressive | $1,000/mo | 15% | 5.6 years |
| Compound only | $0 | any realistic | Not viable |

Contributions must be money the operator can afford to lose entirely. The operator picks in [RFC-0001 §9](08-RFC-0001-v2-architecture.md).

## 9. Product capabilities

**P0 (needed before any v2 live transaction)**
1. Chain-reconciled double-entry ledger with NAV in USD and ETH.
2. One money path: intent, plan, simulate, risk gate, approve, sign, reconcile.
3. Gas guard, kill switch, allowlist with pinned contract code.
4. Independent auditor that can halt.
5. Truthful dashboard and weekly report.

**P1 (S0 earning engine)**
6. Evidence-based program registry and airdrop EV model.
7. Claim watcher for wallets already positioned.
8. USDC parking and LP evaluation against benchmark.
9. Strategy lifecycle gates and forecast calibration.

**P2 (S1 and later)**
10. Range-managed concentrated LP, incentive harvester, Safe with roles, tax export.

## 10. Success metrics

| Horizon | Metric | Target |
|---|---|---|
| 30 days after cutover | Reconciliation | Within tolerance on 99% of checks |
| 30 days | Out-of-band transactions | 0 |
| 90 days | Net return versus benchmark | Reported per strategy; losers retired |
| 90 days | Forecasts resolved on time | At least 90% |
| 12 months | NAV versus selected plan | Within 15% of the contribution path |

## 11. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Goal unreachable without contributions | High | Stated up front; plan selection is explicit |
| Protocol exploit | Medium | Concentration limits, blue-chip only, pinned code |
| Airdrops never pay at this size | High | Option budget capped; not in the plan |
| Over-engineering for $65 | Medium | Stage gating; S0 build is deliberately minimal |
| Key compromise | Medium | Separate signer, small hot balance, Safe from S1 |
| Market drawdown | High | Core sized for tolerance; ETH exposure disclosed |

This document describes a system design. It is not financial or tax advice.
