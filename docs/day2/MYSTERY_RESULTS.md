# Mystery diagnosis results

Source: `runs/mystery_trials.jsonl`. Each row is a recorded sandbox trial; wrong guesses and diagnosis errors are retained.

Smoke run only: trials 1–3, recorded on 11 October 2026, approximately 00:23–00:26 IST. N = 3 recorded attempts. The scheduled eight-or-more-trial evaluation from 11:00 IST is still pending.

## Before fix

| Trial | Hidden fault / target | Guess / target | Top-1 | Top-3 | Target-only | Detect (s) | Diagnose (s) | memory_hit |
|---|---|---|---|---|---|---|---|---|
| 1 | kill / redis | kill / worker | no | yes | no | 0.54 | 21.13 | False |
| 2 | latency / redis | kill / db | no | no | no | not measured | 16.39 | False |
| 3 | kill / worker | kill / db | no | no | no | 0.54 | 22.37 | False |

Accuracy: top-1 0/3; top-3 1/3; target 0/3.

Top-1: 0%; top-3: 33.3%; target-only: 0%. Accuracy is low in this smoke run. Trial 2 failed to inject its selected fault and is retained in the requested all-attempts totals rather than hidden. Restricting to the two trials whose injection logs say OK gives top-1 0/2, top-3 1/2 and target 0/2; this is not the scheduled evaluation.

This is a small sample, not an accuracy guarantee. Top-1 and top-3 require both fault and target to match. Target-only ignores the fault type.

Memory may learn from earlier correct reveals, so these sequential trials are not independent tests of an untrained model. Diagnosis can use rules, confirmed memory, or an LLM; these totals measure the complete system, not LLM accuracy alone.

## Wrong answers and errors

- kill / redis → kill / worker: 1 trial(s).
- kill / worker → kill / db: 1 trial(s).
- latency / redis → kill / db: 1 trial(s).

## Validation limits

- Evidence checked: `runs/mystery_trials.jsonl` and `runs/auto_20261011_002316/events.log`. The log records successful injections/restorations for trials 1 and 3. Trial 2 reports: `image nicolaka/netshoot not pulled - run: docker pull nicolaka/netshoot`. Its detection time is unavailable, not zero; latency-fault diagnosis was not validated.
- Trial 1 confused the injected Redis kill with the worker crash observed in the same window. Redis kill was present in its top three. Trial 3 guessed database kill despite the worker being the selected target; the saved guess has no evidence. Trial 2 also has no saved evidence, and its selected Redis latency fault never successfully injected. These results do not establish a pause-versus-kill confusion: no pause trial was run in this sample.
- The event log confirms live LLM calls for all three trials and rate-limit retries. Nevertheless, all saved guesses contain the deterministic fallback hypothesis. The model's logged conclusion is not necessarily the validated, saved prediction. The exact validation rejection reasons are not recorded, so these totals cannot be claimed as standalone LLM accuracy.
- Answer leakage review: source inspection shows injection fields are removed by `redact()` and the blind agent constructs a measurement whitelist with an opaque incident identifier. The inspected event log keeps injection/restoration labels hidden until reveal; service names in measured evidence are legitimate diagnostic inputs. No direct hidden-answer disclosure was found in the inspected path. Full serialized model prompts/tool responses were not audited, so this is a scoped check, not a guarantee of zero leakage.
- Offline check: not yet run for this evaluation. Current blind diagnosis bypasses the LLM when offline and uses rules or confirmed memory. An offline success alone does not prove LLM cached-answer replay.
- No memory hits were recorded (0/3). This run does not demonstrate successful memory retrieval.
- Smoke, scheduled evaluation and offline runs must be identified separately by trial range; the JSONL does not record offline mode. Keep offline rows outside the live evaluation accuracy denominator.

## Before the scheduled evaluation

Pull the missing `nicolaka/netshoot` image and verify injector prerequisites before repeating latency trials. Diagnose why live LLM conclusions fall back, and preserve fault-window evidence for transient failures instead of relying on healthy post-restoration state. Repeat the smoke check after fixes; retain this original result as the pre-fix record. At or after 11:00 IST, record at least eight further trials and report their own N and accuracy without concealing failed injections or wrong answers.

## Step 1: diagnostic run before repairs

Trials 4–6 were run with rejection logging enabled before normalization and ranking changes. Top-1 2/3, top-3 2/3, target 2/3. These are separate from both the original smoke run and the after-fix run.

| Trial | Hidden fault / target | Guess / target | Top-1 | Top-3 | Target-only | Detect (s) | Diagnose (s) | memory_hit |
|---|---|---|---|---|---|---|---|---|
| 4 | kill / db | kill / db | yes | yes | yes | 0.26 | 18.38 | false |
| 5 | kill / worker | kill / db | no | no | no | 0.26 | 5.92 | false |
| 6 | kill / result | kill / result | yes | yes | yes | 0.27 | 0.45 | false |

The new live log `runs/auto_20261011_005454/events.log` records trial 5 rejection: `primary fault/target differs from top3[0]`. Trial 4 returned a valid AI answer. Trial 6 did not invoke AI because the old rule confidence threshold prevented it.

Replaying older cached answer objects through the instrumented validator (no new model calls) additionally exposed: `top3 weights must be descending and sum to 1`, `unknown fault or unconfigured target in top3` (probe `vote_write` used as a service), and invalid primary `none` fault/target labels. The latter invalid labels remain rejected after repairs.

## After fix

Trials 7–9, recorded approximately 01:02–01:06 IST on 11 October 2026. Source: `runs/mystery_trials.jsonl` and `runs/auto_20261011_010220/events.log`. N = 3. All three injection and restoration entries report OK, including latency after installing netshoot.

| Trial | Hidden fault / target | Guess / target | Top-1 | Top-3 | Target-only | Detect (s) | Diagnose (s) | memory_hit |
|---|---|---|---|---|---|---|---|---|
| 7 | kill / redis | kill / worker | no | no | no | 0.56 | 32.93 | false |
| 8 | latency / redis | latency / vote | no | yes | no | not measured | 35.19 | false |
| 9 | pause / db | kill / db | no | no | yes | 0.72 | 29.53 | false |

Accuracy: **top-1 0/3; top-3 1/3; target 1/3**. Memory hits: 0/3. This is a small sample, not a guarantee. The random fault selections differ from the original smoke run, and its latency injection failed; these are not paired benchmark results. Do not claim an accuracy improvement from these data.

Repairs normalize finite weights and ranked pairs, preserve invalid-label/evidence safeguards, prefer failed dependencies over simultaneous consumer failures using the discovered graph, and always invoke AI online. Offline still uses rules or memory without an LLM. Synthetic blind-diagnosis (10 tests), mystery, contract and graph checks passed; these are not live accuracy measurements. Neither redaction nor injection code was changed.

Remaining failures:

- Trial 7: `blind AI unavailable (UnicodeEncodeError); using evidence ranking`. The rule guess chose the downstream worker, and its saved evidence lacks Redis's fault-window death event. Graph ranking can prioritize a recorded failed dependency, but cannot recreate an absent event. This run does not validate a successful AI diagnosis of Redis kill.
- Trial 8: the accepted AI answer chose vote latency instead of Redis latency. Redis latency appears in its top three. Slow request latency and healthy logs read after restoration do not establish that the entrypoint itself is the slow component. Detection was not recorded, despite the successful injection.
- Trial 9: the accepted AI answer identified the database but confused pause with kill. Connection-error logs alone do not distinguish these mechanisms; its root-cause wording overstates the kill hypothesis.

No validation-rejection warning was recorded in this after-fix log. That does not imply every trial successfully used AI: trial 7 had a runtime encoding failure. Stronger fault-window evidence, bounded uncertainty in AI explanations, and the encoding error remain follow-up work. The scheduled eight-or-more-trial evaluation and offline run are still pending.
