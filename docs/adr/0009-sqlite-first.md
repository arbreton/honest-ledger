# ADR-0009: SQLite first, with a defined Postgres trigger

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
One writer, low volume, one operator.

## Decision
Use SQLite in WAL mode with STRICT tables. Move to Postgres only if there are multiple hosts writing, sustained lock contention, or an S2 standby that needs replication.

## Consequences
No database server to run or pay for. Access stays behind a repository layer, which keeps migration feasible.

## Alternatives rejected
Postgres now: cost without benefit.
