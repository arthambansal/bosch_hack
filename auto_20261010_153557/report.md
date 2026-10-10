# ChaosPilot findings report

**Resilience score: 49/100 (grade F)**

Experiments run: 3. Stop reason: experiment budget used.

## Recon (before any attack)
Single points of failure: vote, result, worker, redis, db

- Hypothesis: A crash of any service will not be automatically recovered due to lack of restart policy, leading to service outage.
- Hypothesis: The absence of healthchecks may cause traffic to be routed to unhealthy containers, degrading user experience.
- Hypothesis: Without persistence volumes for vote, result, and worker, data will be lost on container restart, breaking application state.
- Hypothesis: Running only a single instance of redis or db creates a single point of failure; a failure will bring down all dependent services.

## Weaknesses ranked by risk (FMEA)

| Rank | ID | Failure mode | Effect | S | O | D | RPN | Priority |
|---|---|---|---|---|---|---|---|---|
| 1 | E3 | kill db | 1 accepted votes silently lost (data integrity violated) | 10 | 7 | 10 | 700 | High |
| 2 | E1 | kill redis | cascade: worker crashed and never restarted on their own | 9 | 7 | 10 | 630 | High |
| 3 | E2 | pause redis | partial outage (33% of requests failed) | 5 | 3 | 2 | 30 | Low |

## Root causes (InvestigatorAgent)
### E1: The injected KILL fault terminated the Redis service; the worker attempted to resolve the Redis hostname and open a connection, but the DNS lookup failed, leading to a stack trace in GetIp/OpenRedisConnection and an exit code 1. This caused 100% error rate on vote_write and triggered the kill switch.
Confidence: high (by agent)
- evidence: stuck_details.worker.last_logs contains stack trace at Worker.Program.OpenRedisConnection
- evidence: error_rate_by_probe.vote_write = 1.0
- suggested fix: Add retry and graceful handling for Redis connection failures in the worker, and ensure the worker does not crash on DNS resolution errors.

### E2: KILL SWITCH: vote_write error rate 50% >= 50%
Confidence: low (by rules)
- evidence: {'probes': False, 'recovers': False, 'data_loss': True}
- suggested fix: investigate manually

### E3: The injected KILL of the PostgreSQL service terminated all active connections, causing the result_page service to throw a secure_read error and the worker to raise a “Connection is not open” exception, which in turn drove the error rate above the 50% threshold and triggered the kill switch.
Confidence: high (by agent)
- evidence: db logs: "FATAL: terminating connection due to unexpected postmaster exit"
- evidence: result logs: "secure_read" error in be-secure.c:207
- evidence: worker logs: "System.InvalidOperationException: Connection is not open"
- suggested fix: Add a restart policy (e.g., on-failure) to result and worker containers and implement retry logic with exponential backoff for DB connections so that transient DB outages do not immediately raise error rates.

