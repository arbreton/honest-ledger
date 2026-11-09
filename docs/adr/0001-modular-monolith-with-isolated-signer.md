# ADR-0001: Modular monolith with isolated signer and auditor

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
One operator, $65 of capital, and a need for strong isolation around keys.

## Decision
Build one Python application with clear internal modules. Run only two components separately: the Signer and the Auditor, each under its own OS user.

## Consequences
Simple to run and debug. Isolation is placed exactly where the risk is. The internal modules must be kept honest with CI import rules.

## Alternatives rejected
Microservices: operating cost with no benefit. Single process: leaves keys inside the main app.
