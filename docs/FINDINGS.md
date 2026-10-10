# Evidence-backed findings — Day 2 update

## Current evidence boundary

This checkout contains raw evidence for the approved Day 1 E1 run in
`docs/evidence/e1/`. The Day 2 assignment names `auto_20261010_153557` and
`auto_20261010_170117` from Artham's laptop, but those raw folders were not supplied
locally. The statement below is limited to each named run, not a claim about all runs.

| Claim supplied in the assignment | Required evidence | Verification here |
|---|---|---|
| Worker exited with code 1 after Redis kill and stayed down | results.json stuck_details and timed logs | Pending artifacts |
| Combined fault lost 17 of 40 accepted votes | delivery counters, steps and measurement window | Pending artifacts |
| E2 RPN improved from 270 to 30 | fmea.json, verification.json, applied-fix identity/status | Pending artifacts |

These are teammate-reported claims, not measurements independently checked here.
They must be replaced by linked raw records before presenting them as golden-run
results. No scenario JSON is fabricated from these prose numbers.

## Preserved Day 1 measurements

Run `auto_20261010_143539`, source checkout `63e9150ca17af4ed05880d4245e486481f73fcb4`,
ChaosPilot base `9b6fdd82dc4f464a997685d36347a523b05dc10e`.
Source and prebuilt image provenance are distinct; this does not establish the image
was built from that source commit. Human approval covered one Redis kill only.

| Field | Measured value |
|---|---|
| Baseline duration / accepted / delivered | 15 s / 31 / 31 |
| Baseline vote p50 / p95 | 27.3 / 41.3 ms |
| Baseline result p50 / p95 | 21.5 / 32.8 ms |
| E1 status / fault window | Kill-switch abort / 4.5 s |
| Guard breach observations | 3.5, 4.0, 4.5 s; rolling error rate 50% |
| Fault-window voting requests / successes | 3 / 1 |
| Fault-window result requests / successes | 10 / 10 |
| First HTTP error / recovery after restoration | 0.5 s / 1.5 s |
| E1 accepted / delivered / recorded lost | 24 / 24 / 0 |
| Stuck services | None |
| S / O / D / RPN | 7 / 7 / 2 / 98 |
| Single-experiment score | 95 out of 100, grade A |

Raw files: `docs/evidence/e1/results.json`, `baseline.json`, `fmea.json`, `events.log`
and `approval_evidence.json`. Aggregate delivery counts do not prove per-vote delivery.
Occurrence is a scoring prior, not an observed population rate. HTTP recovery is not
proof of end-to-end recovery. End-to-end MTTD/MTTR were unavailable in this run.

## W1 [HYPOTHESIS] and run-specific outcome

Worker source resolves DNS in GetIp before OpenRedisConnection's Redis-only retry
handler; Main catches other exceptions and returns 1. Without a restart policy, a
DNS failure could leave the worker down. Citations are in the preserved hypotheses.
The Day 1 E1 trial did not reproduce that failure. This neither refutes W1 nor
contradicts the later teammate-reported worker crash: the preconditions and evidence
must be compared. Do not label W1 globally unconfirmed or globally confirmed from
this one trial.

## Day 2 code validation and remaining evidence

Report v2 derives impact, prediction/fix/mystery counters, postmortems and rollback
rows. Regression export/replay is tested with labelled canned results. Test logs in
`docs/evidence/day2_*_test.txt` are simulated checks, never Docker experiment evidence.
The reporter cannot reconstruct exact outage intervals from rolling guard summaries;
it explicitly labels its fault-window proxy.

Live replay could not be run from this session: Docker returned permission denied
connecting to `dockerDesktopLinuxEngine`. No live AI evaluation, Day 2 fix/rollback
measurement, mystery accuracy or GitHub Actions success is claimed. The previous
Windows gate failure was historical; the current gate uses a background input thread.

Golden recording, official form submission and teammate run verification remain
pending. See `docs/day2/TEJAS_HANDOFF.md` for exact integration and evidence requests.
