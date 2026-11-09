# ADR-0004: Single money path with signed decision receipts

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
v1's allowlist existed, but live transactions never passed through it.

## Decision
Every transaction passes intent, plan, simulation, Risk Gate and approval. The Signer requires a valid receipt, and re-checks hard limits independently. Anything else observed on-chain is an incident.

## Consequences
Gates cannot be bypassed quietly. Manual actions need declaration. The Risk Gate is critical and needs mutation testing.

## Alternatives rejected
Advisory checks: exactly what failed in v1.
