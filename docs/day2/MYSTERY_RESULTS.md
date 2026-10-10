# Mystery diagnosis results

Source: `runs/mystery_trials.jsonl`. Each row is a recorded sandbox trial; wrong guesses and diagnosis errors are retained.

Smoke run only: trials 1–3, recorded on 11 October 2026, approximately 00:23–00:26 IST. N = 3 recorded attempts. The scheduled eight-or-more-trial evaluation from 11:00 IST is still pending.

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
