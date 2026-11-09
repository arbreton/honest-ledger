# ADR-0005: Mandatory fork simulation

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
The Dolomite deposit, simulated first, worked first time. The unsimulated Morpho deposit ran out of gas.

## Decision
Every plan is simulated on a fork of the latest block. The Risk Gate compares actual balance and allowance changes to what the plan expected. No simulation means no signature.

## Consequences
Catches reverts, honeypots and surprise transfers, at the cost of seconds per transaction. Cannot catch time-delayed malice.

## Alternatives rejected
eth_call only: no full state diff across multi-step plans.
