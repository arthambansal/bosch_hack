# E3 Analysis: PostgreSQL Failure and Recovery

## 1. Objective

Experiment E3 tests how the Voting App behaves when its PostgreSQL database (`db`) is killed. The experiment investigates user-visible failures, dependent-service recovery, and whether accepted votes reach the database.

## 2. Evidence sources

The analysis uses the saved artifacts in the project-root directory `auto_20261010_170117/`:

- `results.json`
- `fmea.json`
- `verification.json`
- `events.log`

The initial E3 result and the later verification rerun are separate observations and must not be treated as one continuous experiment.

## 3. Initial experiment

The initial E3 result was **aborted by the kill switch**.

| Measurement | Observed result |
|---|---:|
| Fault | Kill PostgreSQL (`db`) |
| Status | Aborted |
| Fault window | 1.7 seconds |
| `result_page` requests | 4 |
| `result_page` errors | 75% |
| `vote_write` error rate | 0% |
| Recovery time | Not recorded |
| Stuck services | `result`, `worker` |
| Votes sent | 110 |
| Votes delivered | 110 |
| Votes lost | 0 |
| Kill-switch reason | `result_page` error rate reached 75% |

The event log records PostgreSQL exiting with code 137 and dependent services failing during the outage. The initial run did not recover within the configured timeout.

## 4. FMEA before remediation

The saved `fmea.json` reports:

| Factor | Value | Meaning |
|---|---:|---|
| Severity (S) | 9 | Dependent services failed to recover independently |
| Occurrence (O) | 7 | Configured prior for a single database-kill fault |
| Detection (D) | 10 | The failure was not adequately represented by ordinary health-page observations |
| RPN | 630 | `9 × 7 × 10` |
| Action priority | High | Requires remediation |

Occurrence is a configured assumption, not a frequency estimated from this single experiment.

## 5. Remediation and verification rerun

The event log records application of the generic `restart-policy` fix before verification. The saved verification result is a separate rerun of E3.

| Measurement | Verification rerun |
|---|---:|
| Status | Completed |
| Fault window | 20.4 seconds |
| `vote_write` requests | 41 |
| `vote_write` error rate | 0% |
| `result_page` requests | 41 |
| `result_page` error rate | 0% |
| Recovery time | 0.3 seconds |
| Votes accepted/sent | 62 |
| Votes delivered | 61 |
| Votes lost | 1 |

The event sequence records PostgreSQL, `result`, and `worker` exiting, followed by `result` and `worker` starting again. This supports the conclusion that service recovery improved. It does not establish that all accepted votes were persisted.

The verification record also contains PostgreSQL connection errors and a worker connection failure. These are consistent with the database outage affecting dependent services.

## 6. Before-and-after risk score

The saved `verification.json` reports:

| Factor | Before | After |
|---|---:|---:|
| Severity (S) | 9 | 10 |
| Occurrence (O) | 7 | 7 |
| Detection (D) | 10 | 10 |
| RPN | 630 | 700 |

The RPN increased by 70 points, approximately **11.1%**.

The reason is supported by the FMEA implementation: `core/fmea.py` assigns severity 10 when at least one accepted vote is lost. The verification rerun recorded one lost vote, raising severity from 9 to 10. Occurrence and detection remained unchanged.

This result must not be presented as an improvement in overall risk. The services recovered faster, but the observed data-integrity failure made the risk score worse.

## 7. Interpretation

### What improved

- The dependent services restarted during the verification rerun.
- Recovery was recorded at 0.3 seconds.
- Both measured probes reported zero errors during the verification rerun.

### What remains unresolved

- One accepted vote was not delivered to the database.
- The test does not establish exactly where the vote was lost.
- The zero-error probe measurements do not negate the delivery-audit finding.
- The saved artifacts do not prove that PostgreSQL-specific health-check or recovery overrides caused the observed recovery.

The evidence supports improved service recovery but **does not demonstrate zero data loss**.

## 8. Recommended next experiment

Run a controlled comparison using the same experiment configuration and comparable traffic volume:

1. Record the initial configuration and baseline.
2. Run the PostgreSQL-kill experiment and save all artifacts.
3. Apply the intended recovery fix.
4. Repeat the same experiment with the same safety limits.
5. Compare service recovery time, probe error rates, accepted and delivered votes, queue depth, and stuck services.
6. Recalculate FMEA from the measured results.

Treat the remediation as successful only if the evidence demonstrates the required recovery behavior and no unresolved data-integrity failures. Report any remaining vote loss even if the services restart successfully.

## 9. Conclusion

E3 exposed a PostgreSQL outage that caused dependent-service failures. The verification rerun showed faster service recovery, but one accepted vote was lost and the RPN increased from 630 to 700. The next priority is to reproduce and investigate the data-loss condition, then verify the proposed fix with a controlled rerun.