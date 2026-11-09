# ADR-0003: LLMs stay outside the money path

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
The agent read web content, had shell access and held standing authority over a machine containing the key.

## Decision
LLMs may summarize, research and write reports. They submit only schema-validated candidates into quarantine. They cannot create intents, approve, sign or change code in the money path.

## Consequences
Prompt injection cannot reach funds directly. Some novel opportunities move slower because a human must approve them.

## Alternatives rejected
Agent with guardrails prompt: instructions are not a security boundary.
