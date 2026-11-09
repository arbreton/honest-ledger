# ADR-0010: Base only until S2

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
Gas on Base is about 0.005 gwei, and bridging consumes small accounts. Multi-chain adds registry, indexing and risk work.

## Decision
Base is the only chain until S2. A new chain must clear a written case and the normal gates. The model remains chain-aware via `chain_id`.

## Consequences
Narrower opportunity set and single-chain concentration risk, in exchange for lower complexity. Reviewed at S2.

## Alternatives rejected
Multi-chain now: complexity and bridge costs exceed the expected gain at this size.
