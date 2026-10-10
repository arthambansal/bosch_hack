# Prompt for Artham's assistant: mystery harness, verify-with-rollback, predictions, wiring

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
I own the Experimenter agent, the orchestrator and the safety code, and I integrate everyone's work.

## Your files
core/mystery.py, core/audit.py (new), core/engine.py, agentic/nodes/execute.py, agentic/runtime.py, agentic/state.py,
chaospilot.py, config.json, core/contract_v5.py, tests/test_mystery.py (new), tests/test_contract_v5.py

## Tasks, in priority order

### 1. Mystery mode (core/mystery.py) — contract 4.2, 5, 6
- `menu(cfg)`: build the safe menu from config.json services. Include at least: kill redis, kill db, kill worker,
  kill result, pause redis, pause db, partition worker, latency redis. Each item {id: "M-<fault>-<service>", label in plain
  English, fault, target}. Every item must pass the Safety Governor policy (single fault, sandbox target).
- `run_trial(choice_id, cfg, graph, offline, chosen_by)`: pick the item (or a random one when choice_id is None or
  "random"); build exp {"id": f"M{trial}", "name": "Mystery fault", "steps": [...], "reason": "hidden",
  "hidden": True}; run it with the existing Engine.run_experiment so the kill switch and recovery checks apply.
  - The engine must NOT print or publish the fault while hidden: when exp.get("hidden") is true, the INJECT/RESTORE log
    lines say "[hidden]" instead of the fault and target, and live_state.experiment shows name "Mystery fault" with
    no steps. Keep the real details in the returned result.
  - Detection: record detected_at as the first moment after injection when any of these is true: a guard breach,
    TruthOracle snapshot status != "ok", a probe error, or a sandbox container not running. Record detected_by.
  - Build a REDACTED copy of the result (drop name, steps, faults_injected, reason, hypothesis, prediction,
    prediction_check, abort_reason text that names the target) and call
    agentic.nodes.diagnostician.diagnose_blind(redacted, cfg, graph, offline).
  - Score: top1 = fault and target both match; top3 = any of guess.top3 matches both; target = target matches.
  - Publish live_state.mystery at every state change: injected -> detected -> diagnosed -> revealed (pause 2 s before
    revealing). Append one line to runs/mystery_trials.jsonl. Call diagnostician.remember_confirmed(result,
    answer, guess.root_cause) when the guess was correct, and core.notify.notify("mystery_reveal", ...).
- `wait_loop(cfg, graph, offline)`: start the prober + TruthOracle (core/truth.py), set mystery.state = "idle" and
  run_status = "running", then loop: wait for runs/mystery_request.json (validate choice_id against the menu, delete
  the file when consumed), or a terminal line ("random" or a menu id); run a trial; go back to idle. Ctrl+C or the
  STOP file exits cleanly and restores everything (reuse runtime.finish / faults.panic).
- chaospilot.py: add `mystery` (one random trial) with `--wait` (judge mode loop) and `--trials N` (N random trials in
  a row, cooldown between them, then print an accuracy table).

### 2. Verify with rollback (agentic/nodes/execute.py verify_node) — contract 4.4
- After re-running, compare RPN per fix (use each fix's rows). A fix whose rows all improved -> status "verified".
  A fix where any row got WORSE -> roll it back: re-apply the remaining kept fixes with core.heal.apply_fixes(kept,
  cfg) (an empty list restores the base compose), log "[Verifier] <id> made <row> worse (<before> -> <after>): rolled
  back", status "rolled_back". No change -> "not_improved".
- Publish live_state.fixes = heal.fix_entries(...) updated with status and rpn [{id, before, after}], plus
  patches.suggest_patches(investigations, results) entries. Call notify("fix_verified" / "fix_rolled_back", ...).
- The routing rule stays: verifier -> remediator only if not improved and fix_attempts < 2.

### 3. Truth Oracle + impact + predictions wiring
- agentic/runtime.py: start a TruthOracle(cfg, prober) in start(), publish truth=oracle.snapshot() from the engine's
  publish loop (every 0.5 s is fine, the oracle itself ticks every 2 s), stop it in finish(). On the first transition to
  status "diverged" log LIVE.event("warn", "[Truth] GRAY FAILURE: ...") and notify("gray_failure", ...).
- After each experiment: result["truth"] = oracle.window(t_inject, t_end); LIVE.set(impact=report_extras.impact_of(result)).
- live_state.predictions from results[].prediction_check (shape 4.6).
- notify("kill_switch", ...) when the guard trips; notify("root_cause", ...) after a diagnosis.

### 4. Brief milestone fixes (MUST, before the audit trail)
- Fault-type coverage (brief: "at least 3 failure types"): in agentic/nodes/experimenter.py / core/agent.py, until 3
  different fault types have run, only offer the agent candidates whose type has not been used yet, and refuse
  "finish". Deterministic filter, the AI still chooses among the allowed candidates. Test it.
- Ranked plan (brief: "AI ranks and selects experiments with a short reason"): publish live_state.plan_ranking (contract
  4.8) every turn: the full risk-ranked candidate list (top 10, planner.candidates order), which ones were tried, the
  chosen id and the AI's reason. Also write it into the run folder so the report can show it.
- Golden run command for the demo: `python chaospilot.py autopilot --max 5 --approve` must show >= 3 fault types and
  include the combined E6 (human approval). Check this in the mock test.

### 5. Optional (only if 1–4 are done and tested): audit trail
- core/audit.py: append every LIVE.event to runs/<run>/audit.jsonl with prev_hash and sha256 hash;
  `python chaospilot.py verify-audit [run_dir]` prints OK or the first broken line.

## Tests (tests/test_mystery.py)
Also test: the coverage filter blocks a 2nd kill before 3 types are covered and blocks finish; plan_ranking passes validate_plan_ranking.
Monkeypatch Engine.run_experiment to return a canned result and diagnose_blind to return a canned guess. Check:
menu items pass the Governor; the published experiment and events never contain the hidden target before reveal;
answer is null until revealed; scoring for exact / top3 / target-only / wrong; the request file is validated and
consumed; a bad choice_id is rejected; rollback chooses the right fixes to keep; every published shape passes
core/contract_v5 validators.
