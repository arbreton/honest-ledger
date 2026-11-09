# ADR-0012: Hermes moves to a read-only research and reporting role

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
Hermes has been effectively operating the system, including live actions. It is useful for research, summaries and notifications.

## Decision
Hermes reads exported views and submits candidates. It runs as `latitude` with no access to `v2signer`, the Risk Gate or production code. v2 scheduling uses systemd timers, and v2 approvals use a separate Telegram bot.

## Consequences
Keeps what Hermes is good at, and removes a large attack surface. Requires removing v1's cron authority.

## Alternatives rejected
Keep Hermes as orchestrator: leaves an LLM in control of the money path.
