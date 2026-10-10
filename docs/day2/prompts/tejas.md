# Prompt for Tejas's assistant: never-again scenarios + CI, report v2, deliverables

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
I own the Cartographer agent, the Reporter, and our deliverables (README, docs, video, team form).

## Your files
core/regression.py, scenarios/* (new), .github/workflows/resilience.yml (new), agentic/nodes/reporter.py,
core/report_extras.py, agentic/nodes/cartographer.py, core/code_tools.py, README.md, docs/** except
docs/day2/DAY2_CONTRACT.md, tests/test_regression.py (new), tests/test_report_v2.py (new)

## Tasks, in priority order

### 1. Never again (core/regression.py) — contract 4.7, 5, 6
- `export_scenario(result, investigation, run_dir)`: for a confirmed failure (stuck_services not empty, or votes
  lost > 0, or not recovered) write scenarios/<slug>.json = {id, name, steps, invariants, from_run, evidence}.
  Invariants: "no_vote_loss" if votes were lost, "no_stuck_services" if a service stayed down,
  "recovers_within_s:<n>" from the measured recovery. Evidence = 2-4 quoted lines from the investigation.
  Never overwrite an existing scenario with the same id; return the path or None.
- `replay(path, cfg)`: load the scenario, run its steps once through core.engine.Engine(cfg, graph).run_experiment
  (same Governor limits and kill switch), check each invariant against the result, return
  {scenario_id, passed, details[]} and record last_status/last_run_at in scenarios/.status.json. Never raises.
- `list_scenarios()`: shape 4.7 from scenarios/*.json + .status.json.
- Tell Artham the exact code for `python chaospilot.py replay [path|--all]` (exit code 1 if any scenario fails); he
  adds it to chaospilot.py.
- .github/workflows/resilience.yml: on push/pull_request: ubuntu-latest, checkout, setup-python, pip install -r
  requirements, `python chaospilot.py up`, `python chaospilot.py baseline --seconds 15`, `python chaospilot.py replay
  --all`. No secrets needed (replay uses no AI). Actually push it to a branch and check the GitHub Actions run; only
  claim "CI runs our chaos tests" if you have seen it run. If Docker networking limits break netem faults in CI,
  restrict CI to kill/pause scenarios and say so in the README.
- Before the replay runs, the sandbox must be in its BASE state (no fixes) so the test shows the weakness; add a
  scenario field "expect": "fail_before_fix" vs "pass_after_fix" if you want to show both.

### 2. Report v2 (core/report_extras.py + agentic/nodes/reporter.py) — contract 4.5 and 5
- `impact_of(result)`: votes_lost and votes_accepted from result.delivery; outage_s = time the entry probes were
  failing (from probes / guard log, measured) or the fault window if not measurable; failed_requests_pct from the
  fault-window probe counts; summary in one plain sentence. Must pass validate_impact.
- `scorecard(results, verification, trials)`: predictions right/total (prediction_check, a field that is false makes it
  wrong), mystery accuracy from runs/mystery_trials.jsonl lines, fixes verified / rolled_back / not_improved, memory hits.
- `postmortem(result, investigation, impact)`: Google-SRE style markdown: Summary, Impact (numbers), Timeline (from the
  events with times), Root cause (with evidence quotes), What went well (kill switch), Action items (the fixes and
  the code suggestion).
- reporter.py: add sections "AI scorecard", "Impact", "Postmortems", "Never-again scenarios", "Before / after"
  (RPN per fix with status, including rolled back ones) to report.md and report.html. Keep the deterministic fallback.

### 3. Deliverables
- docs/FINDINGS.md is out of date (it says W1 was not reproduced). Update it from the real runs on 10 Oct
  (runs/auto_20261010_153557 and runs/auto_20261010_170117 on Artham's laptop — ask him for the folders): worker
  crashed with exit code 1 after the Redis kill and stayed down; combined fault lost 17 of 40 votes; E2 RPN 270 -> 30.
  Quote measured numbers only, mark anything else [HYPOTHESIS].
- README.md: what ChaosPilot is in 5 lines, the four proofs, quick start (exact commands), architecture diagram,
  safety design, results table, honest limits, team.
- docs/ARCHITECTURE.md: update to the Day 2 system (Truth Oracle, mystery mode, verify-with-rollback, memory,
  regression/CI, Control Room v2) with one mermaid diagram; remove "snapshot" wording that is now stale.
- docs/TEAM_FORM.md: make it final (remove "draft"), all five names and roles, repo link, video link; confirm with
  Artham how the form is submitted and submit it.
- docs/VIDEO_SCRIPT.md currently says "W1 not reproduced" and "no fix was applied" — that is no longer true. Rewrite it
  for the Day 2 golden run.
- 3-minute backup video (script in docs/VIDEO_SCRIPT.md, follow the talk in DAY2_CONTRACT.md section 9).

## Tests
tests/test_regression.py: export only for confirmed failures, no overwrite, invariant checks pass/fail correctly on
canned results, replay with a fake engine, list shape valid. tests/test_report_v2.py: impact_of / scorecard /
postmortem on canned data; validate_impact passes; scorecard counts match by hand.
