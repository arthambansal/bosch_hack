# Evidence-backed findings

This page summarizes the real run in `auto_20261010_170117`. The source folder is
preserved locally for review. The run executed three experiments and produced a
resilience score of **61/100 (grade D)** before the recorded sandbox fixes, and
**63/100 (grade D)** after them.

## Ranked weaknesses

| Rank | Experiment | Measured weakness | Evidence | Recommended fix |
|---|---|---|---|---|
| 1 | E3: kill db | Database loss cascaded to result and worker; both remained down without automatic restart. | RPN **630** (S9/O7/D10); result and worker exit code 1; recovery not observed in the window; `result_page` error rate 75%; database exit code 137. | Add `restart: unless-stopped` to the affected services, add health checks, and verify worker/database reconnect behavior after restart. |
| 2 | E2: pause Redis | A transient Redis pause caused worker failure and sustained vote-write degradation; health pages alone did not expose the stopped worker. | RPN **270** (S9/O3/D10); `vote_write` error rate 66.7%, p95 2505.7 ms, worker exit code 1, recovery 0.4 s after restoration. | Add restart policy and Redis reconnect/backoff handling; alert on worker process health and queue age, not only HTTP health. |
| 3 | E1: partition Redis | Redis partition caused a major vote-write outage, although the guard restored it and no votes were lost. | RPN **70** (S7/O5/D2); 75% vote-write errors, kill switch after three guards, recovery 0.4 s, 22 accepted and 22 delivered. | Keep the guard and kill switch, add connection retry/backoff around DNS/connect failures, and validate end-to-end recovery in a longer window. |

## What the run proves

- The run recorded **22 accepted and 22 delivered votes with zero recorded loss**
  for E1; aggregate delivery does not prove every individual vote was delivered.
- The Redis partition was detected quickly by the rolling error guard. The database
  failure was harder to detect because health pages recovered while dependent
  containers remained stopped.
- The verifier recorded an **89% RPN reduction for E2 (270 to 30)** after its
  sandbox fix. E3 increased from 630 to 700 in the recorded comparison, so that
  fix is not presented as successful.

## Evidence files

Use the run's `results.json`, `fmea.json`, `verification.json`, `events.log`,
`report.md`, and `report.html` for the underlying records. MTTD/MTTR are reported
only where the Observer measured them; a recovery value after restoration is not
proof that the service recovered automatically. No API key or webhook is stored
in this repository.
