# 09 — SLA / SLO / SLI

*Acuerdos, Objetivos e Indicadores de Nivel de Servicio*

Definitions: an **SLI** is what is measured; an **SLO** is the target; an **SLA** is a commitment with consequences. Each SLI can be recomputed from stored data (NFR-O2). Windows are 30 days rolling unless stated.

**Availability targets exclude declared host downtime in S0.** A laptop cannot deliver 99.9%, and the design is safe at rest ([ADR-0014](adr/0014-hosting-by-stage.md)). Host uptime is tracked and reported anyway.

## 1. Safety SLOs (zero tolerance)

| ID | SLI | SLO | Breach action |
|---|---|---|---|
| SS-1 | Transactions from managed addresses without a receipt or declaration | **0** | Halt, Sev-1 |
| SS-2 | Signatures issued while halted | **0** | Halt, Sev-1, rotate keys |
| SS-3 | Transactions with gas above the cap | **0** | Halt, Sev-1 |
| SS-4 | Non-exact approvals issued | **0** | Halt, Sev-1 |
| SS-5 | Canaries that passed the Risk Gate | **0** | Halt, Sev-1 |
| SS-6 | Interactions with non-allowlisted contracts | **0** | Halt, Sev-1 |
| SS-7 | Secrets found in logs, prompts, reports or git | **0** | Sev-1, rotate |

## 2. Truth SLOs

| ID | SLI | SLO S0 | SLO S1+ |
|---|---|---|---|
| ST-1 | Reconciliations within tolerance | ≥ 99% | ≥ 99.9% |
| ST-2 | Age of latest OK reconciliation while host is up (p95) | ≤ 30 min | ≤ 10 min |
| ST-3 | Dashboard data age while host is up (p95) | ≤ 30 min | ≤ 10 min |
| ST-4 | Auditor NAV versus core NAV, absolute difference | ≤ 0.5% | ≤ 0.25% |
| ST-5 | Hardcoded business values in reported fields (CI) | 0 | 0 |
| ST-6 | Event replay reproduces ledger (weekly) | 100% | 100% |

## 3. Execution SLOs

| ID | SLI | SLO |
|---|---|---|
| SE-1 | Broadcast transactions that succeed on chain | ≥ 98% |
| SE-2 | Simulated gas within 25% of actual | ≥ 95% |
| SE-3 | Intent to broadcast, excluding human wait (p95) | ≤ 2 min |
| SE-4 | Reverts that simulation predicted would succeed | ≤ 1 per 30 days |

## 4. Earning and efficiency SLOs

| ID | SLI | SLO |
|---|---|---|
| SP-1 | Live strategies beating benchmark over 90 days | Each strategy, else retired |
| SP-2 | Gas as % of NAV, per quarter in S0 | ≤ 2% |
| SP-3 | Annualized operating cost as % of NAV (S1+) | ≤ 2% |
| SP-4 | Forecasts resolved by due date | ≥ 90% |
| SP-5 | Brier score on resolved forecasts, after 20 samples | Better than 0.25 |
| SP-6 | LLM runs on unchanged content | 0 |

SP-1 is a target for the system's discipline. It is not a promise of profit.

## 5. Operations SLOs

| ID | SLI | SLO S0 | SLO S1+ |
|---|---|---|---|
| SO-1 | Scheduled jobs that succeed while host is up | ≥ 99% | ≥ 99.5% |
| SO-2 | Position guard windows covered while host is up | ≥ 95% | ≥ 99.5% |
| SO-3 | Halt-class alert latency (p95) | ≤ 60 s | ≤ 60 s |
| SO-4 | Weekly report delivered | 100% of weeks | 100% |
| SO-5 | Backups succeed; quarterly restore passes | 100% | 100% |
| SO-6 | Host availability, reported | Reported only | ≥ 99.5% |
| SO-7 | Operator time per week in normal operation | ≤ 30 min | ≤ 30 min |

## 6. Error budget policy

| Budget state | Response |
|---|---|
| Any Safety SLO breach | Global halt; no resume without written postmortem |
| ST-1 budget over 50% spent | Freeze strategy promotions |
| ST-1 budget exhausted | Halt live actions until fixed |
| SO-1 or SO-2 budget exhausted | Freeze new features; reliability work only |
| SE-1 under target | Reduce caps by half until recovered |
| SP-3 breached | Remove cost before adding features |

## 7. SLA: operator agreement

There is one operator and no outside customer, so this is an internal agreement with defined consequences.

**The system commits to:**
- Never signing outside the money path.
- Showing true NAV, or clearly showing that it cannot.
- Alerting on halt-class events within 60 seconds of detection, while the host is up.
- Delivering a weekly report.

**The operator commits to:**

| Commitment | If missed |
|---|---|
| Respond to approvals within 24 hours | Approval expires; action is dropped |
| Review Sev-1 incidents within 24 hours | System stays halted |
| Declare manual transactions in advance, or within 1 hour | Unattributed halt until declared |
| Keep recovery materials offline and tested | S1 entry is blocked |
| Unlock signer after restarts | System stays read-only; no harm |

**Third parties.** There are no contracted SLAs with RPC providers, protocols, Telegram or Base in S0. Dependencies are handled by redundancy and failing closed. From S1, a paid RPC's published terms apply.

## 8. Incident severity

| Sev | Definition | Response |
|---|---|---|
| Sev-1 | Funds at risk, safety breach, unattributed transaction | Halt; human required; postmortem and new canary |
| Sev-2 | Truth SLO breach, strategy halted | Same-day review |
| Sev-3 | Degraded data or job failure | Weekly review |

## 9. Reference SLI queries

```sql
-- SS-1: unattributed transactions, 30 days
SELECT count(*) FROM events e
WHERE e.type = 'ChainTxObserved'
  AND e.occurred_at > datetime('now','-30 day')
  AND e.tx_hash NOT IN (SELECT tx_hash FROM transactions)
  AND e.tx_hash NOT IN (SELECT tx_hash FROM declarations);

-- ST-1: reconciliation success
SELECT 100.0 * avg(status = 'OK') FROM reconciliations
WHERE ts > datetime('now','-30 day');

-- SO-1: job success
SELECT job, 100.0 * avg(outcome = 'OK') FROM job_runs
WHERE started_at > datetime('now','-30 day') GROUP BY job;
```
