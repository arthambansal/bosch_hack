# Chaos Fault Types and Observed Evidence

## 1. Purpose

ChaosPilot injects controlled faults into the Docker-based Voting App to evaluate service resilience. Each experiment should have a defined fault, a bounded execution window, safety controls, observable outcomes, and saved evidence.

This document distinguishes verified observations from expected behavior. Results from different runs must not be combined into a single experiment.

## 2. Fault types

### 2.1 Kill

**What it does:** Terminates a selected container or service to test whether the system recovers from an unexpected process failure.

**What to measure:**
- Whether the service restarts.
- Recovery time.
- Errors in dependent services.
- Accepted versus delivered votes.
- Services that remain down.

**Observed evidence — E3, PostgreSQL kill**

Evidence directory: `auto_20261010_170117/`

The initial run was aborted by the kill switch after `result_page` errors reached 75%. PostgreSQL exited with code 137, while `result` and `worker` failed to recover within the timeout. The initial run recorded 110 votes sent and 110 delivered.

A separate verification rerun recorded 0.3-second recovery and zero sampled probe errors, but 62 votes were accepted and only 61 delivered. This demonstrates why service recovery and data integrity must be evaluated separately.

### 2.2 Pause

**What it does:** Temporarily suspends a selected container so that its process cannot make normal progress.

**What to measure:**
- Request latency and error rates.
- Queue growth.
- Recovery after the pause is removed.
- Whether dependent services resume independently.
- Vote delivery and loss.

**Observed evidence — E2**

The root-level event log in `auto_20261010_170117/events.log` records an E2 experiment in which the worker crashed and did not return independently after the fault was restored. The run recorded 32 votes delivered out of 32, with no reported loss.

The exact pause target and duration should be confirmed from the corresponding experiment plan and result artifacts before reporting them.

### 2.3 Partition

**What it does:** Disrupts network communication between selected services to test behavior when a dependency becomes unreachable.

**What to measure:**
- Connection failures and request errors.
- Queue depth.
- Recovery after connectivity is restored.
- Dependent-service restarts.
- Accepted versus delivered votes.

**Observed evidence**

The root-level event log records an E1 Redis partition experiment. The kill switch triggered after vote-write errors reached 75%. Following restoration, recovery was recorded at approximately 0.4 seconds, and 22 of 22 votes were delivered.

This result is specific to the recorded E1 run. Confirm the exact target and fault duration from the saved plan before describing the precise network rule.

### 2.4 Latency

**What it does:** Adds network delay to a selected dependency, testing whether the application remains usable under slower responses.

**What to measure:**
- Median (p50) and 95th-percentile (p95) latency.
- Error rates.
- Recovery after removing the delay.
- Throughput and data delivery.

**Observed evidence — E4, Redis latency**

Evidence directory: `runs/run_20261011_004610/`

| Measurement | Baseline | During fault |
|---|---:|---:|
| `vote_write` p50 latency | 10.6 ms | 1,622.5 ms |
| `vote_write` p95 latency | 20.6 ms | 1,628 ms |
| `result_page` p95 latency | 11.2 ms | 10.9 ms |
| `vote_write` error rate | 0% | 0% |

Additional results:
- Injected delay: 400 ms to Redis.
- Fault window: 20 seconds.
- Recovery time: 0.7 seconds.
- Votes accepted: 34.
- Votes delivered: 34.
- Votes lost: 0.
- Stuck services: none.

The observed `vote_write` p95 was approximately 79 times the baseline p95. The request sample counts differed between baseline and fault measurements, so this ratio should be treated as an observed comparison, not a controlled statistical estimate.

### 2.5 Spike

**What it does:** Applies a load or resource spike to test how the application behaves under elevated demand or resource pressure.

**What to measure:**
- Request throughput and latency.
- Error rate.
- CPU and memory pressure, where measured.
- Queue depth and backlog.
- Recovery time and data integrity.

**Evidence status**

The available evidence summarized for this document does not establish a complete, independently verified set of spike metrics. Before presenting a numerical result, inspect the relevant experiment's `plan.json`, `results.json`, `events.log`, and verification artifacts.

Do not infer successful spike handling merely because an experiment completed.

## 3. Cross-experiment observations

1. **Service recovery is not equivalent to data integrity.** E3 recovered quickly in the verification rerun but still recorded one lost vote.
2. **Safety controls matter.** The E1 and initial E3 logs record the kill switch stopping an experiment when the configured error threshold was reached.
3. **Latency can degrade without producing errors.** E4 recorded zero vote-write errors despite a substantial increase in latency.
4. **Run artifacts must remain separate.** Initial experiment results and later verification reruns can have different traffic counts, recovery behavior, and outcomes.
5. **Claims must be evidence-backed.** Missing metrics should be reported as unavailable rather than estimated.

## 4. Minimum reporting checklist

For each experiment, record:

- Experiment ID and fault type.
- Target service and fault parameters.
- Run directory and timestamp.
- Baseline and fault-window measurements.
- Request counts, error rates, and latency percentiles.
- Recovery time and stuck services.
- Accepted, delivered, and lost votes.
- Kill-switch status and reason.
- Remediation applied, if any.
- Verification rerun results.
- Remaining limitations and unresolved failures.

## 5. Conclusion

The available evidence demonstrates that ChaosPilot can expose different resilience problems, including dependent-service failures, kill-switch activation, and severe latency degradation. However, the evidence also shows that a successful restart does not guarantee zero data loss. Final resilience claims must be based on complete, repeatable experiments and explicit verification results.