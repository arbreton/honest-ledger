# ADR-0007: One identity per program, no Sybil farming

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
v1's config planned burner wallets per airdrop. Programs prohibit identity splitting, and filters now remove it at scale; Linea excluded over 500,000 addresses.

## Decision
The system operates one identity per program. Burner wallets for airdrop multiplication are removed. Separate addresses are allowed only for custody and safety, and are never used to multiply eligibility.

## Consequences
Follows program rules and protects the main wallet's eligibility. Gives up the (increasingly poor) multi-wallet route.

## Alternatives rejected
Multi-wallet farming: against program rules, and likely to be filtered.
