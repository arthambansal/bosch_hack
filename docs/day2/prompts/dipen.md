# Prompt for Dipen's assistant: blind diagnosis, failure memory, mystery accuracy

You are my coding partner for the final day of a hackathon (Bosch, "AI-driven chaos engineering for cloud-native
resilience"). Our product is ChaosPilot: a multi-agent system that maps the Docker Example Voting App
(vote -> redis -> worker -> postgres -> result), plans and injects safe faults, diagnoses root causes, applies and
verifies fixes, and reports an FMEA risk score. Judging is Sunday 16:00. Today we add our differentiators.

FIRST, read these files in the repo, in this order, before writing any code:
1. docs/day2/DAY2_CONTRACT.md   (the binding contract: shapes, signatures, file ownership, rules)
2. CONTRACT.md                   (Day 1 contract: results.json, live_state, approval gate)
3. core/contract_v5.py           (validators for every new live_state shape)
4. tests/test_contract_v5.py and tests/test_graph_mock.py
5. The files listed under "Your files" below, and any file they import.

NON-NEGOTIABLE RULES
- Edit ONLY the files listed under "Your files". If you think another file must change, stop and write me the exact
  change so I can ask its owner. Never change a function signature from DAY2_CONTRACT.md section 5.
- The repo is public: never write API keys, webhook URLs or .env files. Secrets come only from environment variables.
- Faults only ever touch the sandbox containers from config.json. Safety logic stays deterministic code.
- Every new function needs a safe fallback: on any error it logs one LIVE.event("warn", ...) line and returns the
  "not available" value from the contract. It must never crash a run.
- No invented numbers. Anything shown to users comes from a measurement, or is shown as null / "not available".
- Write a test file that runs WITHOUT Docker or network (monkeypatch core.common.docker, requests, core.llm.ask_json).
  It prints "PASS ..." lines and ends with "ALL CHECKS PASSED".
- Before you say you are done, run and show the output of:
    PYTHONPATH=. python3 tests/test_contract_v5.py
    PYTHONPATH=. python3 tests/test_graph_mock.py
    PYTHONPATH=. python3 <your new test file>
  All three must end with ALL CHECKS PASSED.
- Keep code simple and readable; comments explain WHY. Python 3.10+, standard library + requests only (no new
  dependencies unless I approve).

WHEN YOU FINISH, give me: (1) a short list of files changed, (2) how to run the feature for real, (3) what I should say
to a judge about it in two sentences, (4) anything you could not finish or verify.

## My role
I own the Diagnostician agent and the Knowledge Store (SQLite memory of experiments, observations, signatures).

## Your files
agentic/nodes/diagnostician.py, core/knowledge.py, core/signatures.py, core/analysis_tools.py, core/tools.py,
tests/test_blind_diagnosis.py (new)

## Tasks, in priority order

### 1. Blind diagnosis: diagnose_blind(res, cfg, graph, offline) — contract 4.2 and 5
Artham's mystery harness injects a hidden fault and gives you a REDACTED result (no name, steps, faults_injected,
reason, hypothesis, prediction). You must name the fault type and the target service from evidence only.
Return {fault, target, confidence 0..1, top3[{fault,target,confidence}], root_cause (one sentence),
evidence[quoted lines or measurements], memory_hit, seconds}. fault ∈ kill|pause|partition|latency|spike,
target ∈ config.json services. Must pass core.contract_v5.validate_guess.

Do it in three layers, cheapest first:
a. Memory (instant): extract features from the Observer summary (load_observation(res["id"]) +
   signatures.extract_features) and call KnowledgeStore.similar_signatures. If the best confirmed match has
   similarity >= 0.8, answer from it (memory_hit True) and publish live_state.memory (shape 4.3) with saved_s measured
   against the stored time of the original AI diagnosis.
b. Deterministic evidence scoring (always runs, also the fallback): build a score for every (fault, target) pair from
   measured symptoms. Useful discriminators — verify each one against real runs before trusting it:
   - container state from list_containers: "exited"/missing -> kill; "paused" -> pause.
   - docker events in the observation (die/kill/pause/network disconnect) name the container directly.
   - which probe failed: vote_write only -> redis or vote side; result_page only -> db or result side; both -> shared.
   - latency up but low error rate -> latency; timeouts with the container running -> pause or partition.
   - partition: container running and not paused, but its network calls fail (check `docker inspect` networks).
   - stuck_services and worker exit code 1 + DNS log lines -> redis disappeared.
   Turn scores into confidences that sum to 1 over the top 3.
c. AI reasoning (only if layer b is not confident, i.e. top confidence < 0.6, and not offline): the existing ReAct
   investigate() with read-only tools, given the redacted result and layer-b candidates; it must cite evidence. If the
   AI answer is invalid, keep layer b.
Record `seconds` (wall time).

### 2. remember_confirmed(res, fault, root_cause)
Save a CONFIRMED signature with signatures.build_signature (fault = the true {type, target}) after a mystery
reveal that was correct or a verified fix. Include the original diagnosis duration so saved_s can be computed later.
Repeated identical signatures must not pile up duplicates.

### 3. Mystery trials tomorrow (with Artham, 11:00–12:15)
Run `python chaospilot.py mystery --trials 8` (Artham builds the command). Produce docs/day2/MYSTERY_RESULTS.md:
table per trial (answer, guess, top1/top3/target, seconds to detect, seconds to diagnose, memory hit) and totals,
from runs/mystery_trials.jsonl only. Note which faults are confused (e.g. pause vs partition) and why.

## Tests (tests/test_blind_diagnosis.py)
Canned redacted results + observations for each menu item (kill redis, kill db, kill worker, pause redis, pause db,
partition worker, latency redis): check the deterministic layer ranks the truth first or in top 3; memory hit path
returns memory_hit True and publishes a valid memory shape; invalid AI output falls back; the function never reads
redacted keys (assert by passing a result without them); every output passes validate_guess.
