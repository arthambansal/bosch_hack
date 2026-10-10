# Evidence-backed findings — 10 Oct 2026

## Provenance

- ChaosPilot base: `9b6fdd82dc4f464a997685d36347a523b05dc10e`.
- Inspected Voting App source: `63e9150ca17af4ed05880d4245e486481f73fcb4`.
- Actual experiment: `runs/auto_20261010_143539`; preserved relative copies in `docs/evidence/e1/`.
- No API key configured; source-derived Cartographer and report fallbacks ran. Source checkout and prebuilt Docker image provenance are distinct: this run does not establish that the image was built from that exact source commit.
- User explicitly approved E1 Redis kill. No combined faults or configuration fixes ran. The earlier full-graph attempt failed before injection; it is not experiment evidence.

## Healthy baseline [MEASURED]

15 seconds: vote_write 31 requests, 31 successful, p50 27.3 ms, p95 41.3 ms; result_page 31 requests, 31 successful, p50 21.5 ms, p95 32.8 ms. Delivery audit: 31 accepted, 31 delivered. This is aggregate row-count evidence, not unique canary tracing.

## E1 Redis kill [MEASURED]

| Field | Recorded result |
|---|---|
| Status | aborted by kill switch |
| Fault window | 4.5 s |
| Guard observations | breaches at 3.5, 4.0, 4.5 s; rolling error rate 50% |
| Fault-window vote probe | 3 requests, 1 successful; error rate 0.667; p95 2538.7 ms |
| Fault-window result probe | 10 requests, 10 successful; p95 26.4 ms |
| First HTTP error | 0.5 s from injection |
| HTTP recovery | 1.5 s after restoration; three-success streak |
| Delivery audit | 24 accepted, 24 delivered, 0 recorded lost |
| Stuck services | none |
| FMEA | S=7, O=7, D=2; RPN=98, Medium priority |
| Resilience score | 95/100, A, for this single recorded experiment only |

The fault-window request error rate differs from the rolling guard rate because the windows differ. The score is computed by the existing deterministic scorer; occurrence is a documented scoring prior, not an observed population frequency. A single short aborted test does not establish general resilience or zero possible loss.

## W1 source hypothesis [FROM SOURCE] [HYPOTHESIS]

`worker/Program.cs:108` calls `GetIp` before the Redis retry loop; line 118 catches only `RedisConnectionException`; lines 126–131 resolve DNS via `Dns.GetHostEntryAsync`; `Main` catches `Exception` at line 62 and returns 1 at line 65. If DNS resolution fails, this path can exit the worker. The sandbox compose has no worker restart policy.

**Outcome:** W1 was **not reproduced** by this Redis-kill trial. No worker exit or stuck-worker evidence was recorded. H1 stays `open`; it is neither confirmed nor refuted because the DNS-failure precondition was not observed. The blueprint's historical W1 measurement is supplied context, not a measurement made in this session. No DNS-error log is invented.

## Proposed follow-up [HYPOTHESIS]

After separate human approval, test a discriminating DNS-resolution failure under the sandbox policy and gather worker exit timestamps, logs, queue depth, DB growth and unique canary delivery. Pin source/image provenance before attributing exact source behaviour to an image. Retry/backoff and restart policy are proposed mitigations only; no before/after improvement, RPN reduction or trade-off is claimed.

## Blockers and limits

- Observer canary/timestamp module is absent at this base. End-to-end MTTD and MTTR are unknown; 0.5 s and 1.5 s above describe HTTP probes only.
- Full CLI approval fails on Windows: `OSError: [WinError 10038] An operation was attempted on something that is not a socket`, in `agentic/graph.py` `select.select([sys.stdin], [], [], 0.5)`.
- `--max 1` rule fallback selected `COMBINED: worker down, then redis crash`; no approval was given for that proposal and no injection ran. Single E1 was executed with the documented harness.
- Current Governor requests approval for combined faults only, weaker than the blueprint's data-store-kill gate. External approval was obtained for E1. Artham must integrate the complete rule.
- No live LLM run, fix verification, regression/trade-off measurements, mystery trials, or second laptop. The blueprint definition of done is therefore not fully met.
- No official team form or full member/contact details were supplied. Team form remains a draft.
