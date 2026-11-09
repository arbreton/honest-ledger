# ADR-0006: Capabilities unlock by capital stage

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
Actions and infrastructure that make sense at $50k are harmful at $65. For instance a $5/month VPS costs about 92% of NAV per year.

## Decision
Four NAV-based stages (Seed, Build, Scale, Preserve) control strategies, custody, hosting and caps. Each has entry gates that require both capital and clean history.

## Consequences
Costs stay proportional and risk is earned. Early stages may look underpowered, which is intended.

## Alternatives rejected
Full platform up front: expensive and unsafe. Pure manual forever: no path to scale.
