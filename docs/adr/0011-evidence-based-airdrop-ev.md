# ADR-0011: Evidence-based airdrop valuation

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
v1's EV figures, including "$43 Base token", were typed by hand and backed by affiliate pages. Base has confirmed no token terms.

## Decision
Each program has an evidence class (E0–E4) that caps its probability. Value comes from share-of-pool once points or allocation are published. Unknown programs are valued at zero marginal EV and allowed only near-zero-cost actions. Forecasts are stored and scored.

## Consequences
Fewer speculative actions, and judgment becomes measurable. It will look conservative relative to airdrop blogs.

## Alternatives rejected
Hand-tuned estimates: not falsifiable.
