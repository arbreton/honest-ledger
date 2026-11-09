# ADR-0008: Custody: capped legacy EOA, then Safe with Roles

*Architecture Decision Record*

**Status:** Proposed · **Date:** 2026-11-08 · **Decider:** Operator

## Context
The current key has been readable from the agent's account. A new wallet would be safer but abandons history that may matter for airdrops. The funds at risk are small.

## Decision
Keep the EOA with a hot balance of at most $100 in S0. Contributions above that go to an operator-held vault the bot cannot access, tracked watch-only. At S1, deploy a Safe with fresh owners and Zodiac Roles restricting the bot key to allowlisted targets and functions.

## Consequences
History retained; compromise is bounded. Two addresses to track. Safe activity starts with its own fresh history.

## Alternatives rejected
Rotate immediately: loses history to protect about $65. Safe now: more complexity than S0 can use.
