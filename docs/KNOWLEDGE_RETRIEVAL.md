# Structured failure-case retrieval

The Diagnostician retrieves confirmed historical signatures and their recorded
observations from `runs/knowledge.sqlite3`. This uses measured symptom similarity
(Jaccard >= 0.6) or exact normalized log patterns. It requires no embeddings,
external vector database, or additional LLM inference calls. A match is a lead,
not confirmation of the current incident. Scores are not probabilities.

## Register a reviewed case

First collect an actual observation through the existing experiment pipeline.
Review that observation, its logs, and the claimed cause yourself. An injected
fault does not establish a deeper application weakness or unmeasured impact.
Do not mark an LLM answer confirmed merely because it sounds plausible.

Prepare a JSON file using the existing Section 8.2 FailureSignature fields:
`id`, `from`, `fault`, `features`, `root_cause`, `confirmed`.
Use a unique signature ID. `from` must match an observation already in the store.
`fault` must contain `type` and `target_role`. Features must use the existing
binary feature names; omit unknown measurements rather than guessing zeros.
Set `confirmed` to true only after your manual review.

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m core.knowledge runs\reviewed_signature.json --confirm
```

This preserves existing observations and rejects a signature ID already used
with different content. It stores no new JSON fields or database columns. Manual
confirmation is a reviewer assertion; it is not automated intervention proof.

## Retrieval and limitations

`store.similar_signatures(features)` remains unchanged for existing callers.
`store.retrieve_cases(features, observation, exclude_experiment=incident_id)`
returns an internal prompt packet with at most three confirmed cases, their
source IDs, compared features, matching log snippets and recorded metrics.
Cases without a source observation are skipped. The current incident is excluded.
Missing measurements stay null. Matches are deterministic: log-match count,
then symptom similarity, then signature ID.

Log matching normalizes changing numbers and IP addresses using the Observer's
normalizer. It matches identical normalized text, including across service names;
historical service names remain visible. This is not semantic similarity and
generic log text can match unrelated causes. Check topology and current evidence.

The current store uses experiment IDs as keys. Reusing `E1` in later runs may
replace its observation. For now, only register cases with unique experiment IDs
and retain the original run artifacts. Run-scoped history needs separate work.
Synthetic checks are not automatically imported into the real store.

## Verify

```powershell
.\.venv\Scripts\python.exe tests\test_knowledge_retrieval.py
```

These tests use explicitly labeled synthetic cases in a temporary database.
They validate storage and retrieval behavior, not live LLM diagnosis accuracy.

## Memory-first diagnosis and verified solutions

Before constructing the LLM agent, `investigate()` checks for a known case with
a reviewed, verified fix. The initial conservative shortcut requires:

- One known injected fault with the same type and target role.
- At least three jointly measured binary features, with no disagreement.
- An exact normalized error pattern from the same service.
- No competing cause among matching cases and exactly one verified fix.

Every candidate is checked for ambiguity, not just the top three. When these
conditions hold, the Diagnostician returns a historical explanation and a
previously verified recommendation with zero LLM calls. Confidence remains low:
the current cause is not independently confirmed. Existing output fields and
`by=rules` are retained; evidence and events identify memory reuse explicitly.
The shortcut recommends a change; it never applies a fix or bypasses approval.

Otherwise normal LLM investigation receives retrieved cases and up to two
verified fix recommendations per case. Unknown spontaneous faults, combined
faults, missing logs, and ambiguous cases retain the reasoning path. Context
fingerprints/code-version matching are not implemented; check applicability
before applying any historical fix.

Register a solution using complete, unchanged Section 8.2 Diagnosis,
FixProposal, and VerificationReport JSON files. The diagnosis cause must exactly
match a confirmed signature. `fix.for` links its diagnosis, `report.fix` links its
fix, and the verification plan must rerun the signature's source experiment.

```powershell
.\.venv\Scripts\python.exe -m core.knowledge runs\confirmed_signature.json --confirm --diagnosis-file runs\reviewed_diagnosis.json --fix-file runs\reviewed_fix.json --verification-file runs\measured_verification.json
```

The registering reviewer must check real provenance, applicability and regression
guards. Registration checks measured improvement in every requested metric
(`mttr_s`, `delivery_ratio`, or `rpn`), required repetition counts, a nonempty
regression report and `decision=keep`. All after samples must improve; unknown
before values cannot prove improvement. Regression guard text is human-reviewed,
not automatically interpreted. These checks cannot authenticate fabricated input.

`fixes(id,json)` and `verifications(fix_id,json)` use the existing Section 9 tables.
Registration is atomic and refuses changed existing records. No production
pipeline automatically writes verified fixes yet; this is an explicit reviewed
registration interface. Existing Redis pause/kill cases have no verified fix and
no matching diagnostic error logs, so they do not trigger the shortcut.

```powershell
.\.venv\Scripts\python.exe tests\test_memory_first.py
```

This suite uses synthetic cases in temporary storage and asserts the LLM agent
is never constructed on the verified-memory path. It does not establish live
fix efficacy.
