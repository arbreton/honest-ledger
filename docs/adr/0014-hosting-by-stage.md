# ADR-0014: Hosting follows stage, safe at rest

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
The WSL laptop lost 98.8 hours in 12 days. A VPS would cost about 92% of NAV per year.

## Decision
S0 stays on the existing PC, and positions must be safe when the bot is off. Move to a VPS from about $3,000 NAV, when about $60 a year is 2% or less. A warm standby comes at S2 or later.

## Consequences
S0 availability is limited and accepted. Automation that depends on uptime waits until S1.

## Alternatives rejected
VPS now: disproportionate cost. Serverless: unsuitable for key isolation.
