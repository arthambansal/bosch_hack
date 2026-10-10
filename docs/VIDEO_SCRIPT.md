# Three-minute captioned evidence walkthrough

This video presents the actual implementation and one real test. It is an evidence walkthrough, not a recording of an unperformed full demo. No voice track; captions carry the narrative.

| Time | Caption / evidence |
|---|---|
| 0:00–0:30 | ChaosPilot: governed chaos in an isolated Voting App sandbox. User → vote → Redis → worker → DB; result reads DB. |
| 0:30–1:00 | Cartographer source tools are confined and read-only. W1 cites Program.cs GetIp, OpenRedisConnection, Main; Hypothesis is open. |
| 1:00–1:30 | Real healthy baseline: 31/31 accepted votes delivered; vote p95 41.3 ms; result p95 32.8 ms. |
| 1:30–2:00 | Human-approved Redis kill; Guard breaches at 3.5, 4.0, 4.5 s; kill switch restores Redis. First HTTP error 0.5 s. |
| 2:00–2:30 | Result: HTTP recovery 1.5 s after restore; delivery 24/24; no stuck worker. W1 not reproduced. No fix was applied. |
| 2:30–3:00 | Reporter: RPN 98, single-test score 95/100; fault tree and heatmap. End-to-end MTTD/MTTR unknown. Full AI, fixes and second-laptop validation remain pending. |

Raw evidence is in `docs/evidence/e1/`. The wider blueprint's proposed mystery-fault, fix and audit scenes are not presented as completed work.
