# ADR-0002: Event-sourced double-entry ledger as system of record

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
v1's numbers could not be trusted: 996 fake outcomes, stale balances, values scraped from logs.

## Decision
All state changes are append-only, hash-chained events. Balances come from balanced double-entry postings, reconciled against the chain. A breach halts the system.

## Consequences
Numbers can be replayed and audited. Costs attribute properly. More upfront work, and accrual events must be modelled carefully.

## Alternatives rejected
Balance snapshots only: cannot explain changes or attribute gas. Third-party portfolio tracker: not attributable to strategies.
