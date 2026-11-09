# ADR-0013: Independent auditor with halt-only authority

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
All 2,646 v1 audits passed, partly because the Auditor reused Hunter's data and could not disagree.

## Decision
The Auditor is separate code under a separate user. It recomputes NAV and attribution from raw chain data through its own RPC path, and runs adversarial canaries through the real Risk Gate. It can halt but cannot approve or sign. A run where nothing could have failed is itself a failure.

## Consequences
Some logic is deliberately duplicated. Its usefulness relies on the canary set continuing to grow.

## Alternatives rejected
Shared-library auditor: repeats v1's blind spot. LLM auditor: suggestive but not verifiable, so supplementary at most.
