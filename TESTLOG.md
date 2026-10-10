# ChaosPilot Test Log

## Environment
- Application: Docker Example Voting App
- Environment: Local Docker Desktop sandbox
- Experiment: E1 — Kill Redis
- Run ID: run_20261010_121055
- Evidence: runs/run_20261010_121055/

## Objective
Verify controlled fault injection, safety-guard activation, automatic restoration, application recovery, and vote delivery.

## E1 Results

| Check | Actual result |
|---|---|
| Fault injection | Successful |
| Vote-write error rate during fault | 100% |
| Guard threshold | 50% |
| Consecutive guard breaches | 3/3 |
| Kill switch | Triggered |
| Experiment status | Aborted by the safety guard, as expected |
| Fault window | 2.2 seconds |
| Redis restoration | Successful |
| Recovery time | 0.4 seconds |
| Result-page probe | 5/5 successful |
| Vote-write probe during fault | 0/5 successful |
| Votes accepted | 13 |
| Votes delivered | 13 |
| Reported vote loss | 0 |

## Event Timeline
- 12:10:58 — Experiment started.
- 12:11:09 — Redis kill injected successfully.
- 12:11:10 — First and second guard breaches recorded.
- 12:11:11 — Third breach triggered the kill switch.
- 12:11:11 — Redis restoration reported successful.
- 12:11:12 — Recovery confirmed in 0.4 seconds.
- 12:11:18 — Delivery check reported 13 accepted, 13 delivered, zero loss.
- 12:11:23 — Run evidence saved.

## Conclusion
E1 demonstrated successful fault injection, detection of a 100% vote-write error rate, safety-guard activation, restoration, and recovery. The delivery check reported no loss among 13 accepted votes.

The status "aborted" represents the intentional safety stop, not an uncontrolled experiment failure.

## Limitations
- This was one local sandbox run.
- Repeated runs are needed to establish consistency.
- The report command was unavailable because core/report.py was not ready at test time.
- Zero reported vote loss in this run does not establish production-scale reliability.

## Next Tests
- Repeat E1 to assess consistency.
- Independently verify the manual kill switch.
- Review safety and restoration before running additional fault experiments.
