# ChaosPilot Day 2 contract (v5)

Every teammate's AI assistant reads this file first. If anything here conflicts with your prompt, this file wins.
Questions go to Artham. Only Artham edits this file, `agentic/state.py`, `core/contract_v5.py`, `config.json`,
`chaospilot.py` and `agentic/runtime.py`.

## 0. What we are building and why

Pitch: **"Other AI chaos tools suggest. ChaosPilot proves."** Four proofs:

1. **Truth Oracle (gray-failure detector).** Health checks can say "healthy" while users are hurt (Microsoft calls this a
   gray failure). We send uniquely tagged canary votes and check that each one reaches Postgres. When monitoring is green
   but votes stop arriving, the dashboard shows **GRAY FAILURE**.
2. **Mystery mode (blind diagnosis).** A judge, or a random draw, picks a fault. It runs under the same Governor and kill
   switch. The agents are never told what it was; they must name the fault and the target from evidence. We reveal the
   answer and keep a measured accuracy table.
3. **Fix with proof and rollback.** A fix is kept only if the re-run lowers risk (RPN). A fix that makes things worse is
   rolled back automatically. Code fixes are shown as diffs and never applied automatically.
4. **Never again.** Every confirmed failure becomes a replayable scenario file plus a GitHub Actions workflow that fails the
   build if the failure comes back.

Supporting features: failure memory (instant diagnosis of a known failure), impact in human terms, an AI scorecard in
the report, an auto-postmortem, Discord alerts, a Control Room v2, and an audit trail (optional).

## 1. Rules (unchanged from Day 1, still binding)

- Repo is PUBLIC. Never commit API keys, `.env`, webhook URLs. Secrets come only from environment variables.
- Faults only touch sandbox containers. Safety stays deterministic code. The AI never edits files or runs commands.
- Every new function has a safe fallback: if it fails, the run continues and the dashboard shows "Not available".
- `python3 tests/test_graph_mock.py` and `python3 tests/test_contract_v5.py` must print ALL CHECKS PASSED before you push.
- Edit only files you own (section 2). Push to your own branch. Artham merges to `main`.
- Never present a hypothesis as a result. Every number on screen or in the report comes from a measurement.

## 2. Ownership (new or changed files)

| Person | Owns (edit freely) | Delivers |
|---|---|---|
| Artham | `core/mystery.py`, `core/audit.py`, `agentic/nodes/execute.py`, `agentic/runtime.py`, `core/engine.py`, `agentic/state.py`, `core/contract_v5.py`, `config.json`, `chaospilot.py` | Mystery harness, verify-with-rollback, prediction scoreboard, wiring of everyone's functions, audit trail (optional) |
| Pratham | `core/truth.py`, `core/probes.py`, `core/heal.py`, `core/patches.py`, `sandbox/patches/*`, `agentic/nodes/remediator.py`, `sandbox/fixes/*` | Truth Oracle, code-patch suggestion, fix entries, why E3 got worse |
| Dipen | `agentic/nodes/diagnostician.py`, `core/knowledge.py`, `core/signatures.py`, `core/analysis_tools.py`, `core/tools.py` | Blind diagnosis, memory-first diagnosis, mystery trials and accuracy table |
| Samridhi | `dashboard/**`, `core/notify.py` | Control Room v2, `/mystery` and `/runs` endpoints, Discord alerts |
| Tejas | `core/regression.py`, `scenarios/*`, `.github/workflows/resilience.yml`, `agentic/nodes/reporter.py`, `core/report_extras.py`, `agentic/nodes/cartographer.py`, `core/code_tools.py`, `README.md`, `docs/**` (except this file) | Never-again scenarios + CI, report v2 (scorecard, impact, postmortem), updated FINDINGS, README, video |

Stub files for every new module are already on `main` with the exact signatures below and safe defaults, so the whole
system runs before anything is implemented. Replace the stub body; never change a signature without asking Artham.

## 3. Timeline (judging Sunday 16:00, 10 minutes)

| When | What |
|---|---|
| Sat 21:30–01:00 | Everyone builds their flagship against mocks; unit test passes; push to own branch by **01:00** |
| Sat 01:00 | Artham merges, runs all tests, pushes `main` |
| Sun 09:00 | Everyone pulls `main`; mock tests; one real smoke run on two laptops |
| Sun 10:30 | Fixes from smoke run merged. Full live autopilot with healing |
| Sun 11:00–12:15 | Mystery trials, at least 8 (Dipen + Artham). Accuracy table into the report |
| Sun 12:30 | **Feature freeze.** Only bug fixes after this |
| Sun 13:00 | Golden run recorded (for `--offline`), backup video recorded, report generated |
| Sun 13:30–15:15 | Slides + rehearse the 10-minute talk three times, with live demo |
| Sun 15:15–16:00 | Buffer. Laptops charged, Docker up, dashboard open, baseline run |

## 4. Live state keys (runs/live_state.json, read by the dashboard)

Existing keys are unchanged (see CONTRACT.md). New keys below. **A missing key means "not available" and the UI must say
so; never show 0 for a missing value.** Timestamps are epoch seconds. Validators for every shape live in
`core/contract_v5.py`; call them in your tests.

### 4.1 `truth` — produced by Pratham (`core/truth.py`), published by Artham's runtime every tick
```json
{
  "status": "ok | diverged | down | unknown",
  "monitoring": "healthy | degraded | unknown",
  "canaries": {"sent": 12, "stored": 9, "pending": 1, "suspected_lost": 2, "last_lag_s": 0.41, "grace_s": 10},
  "invariants": [
    {"name": "every_vote_counted", "ok": false, "detail": "2 canaries not in Postgres after 10 s"},
    {"name": "worker_running",     "ok": false, "detail": "chaos-worker exited (code 1)"},
    {"name": "queue_drains",       "ok": true,  "detail": "redis 'votes' length 0"}
  ],
  "diverged_at": 1791631290.2,
  "updated_at": 1791631301.0
}
```
Rules: `monitoring` is "healthy" when every probe's recent error rate is below the kill-switch ceiling. `status` is
`unknown` with no canary data yet, `down` when monitoring is degraded, `diverged` when monitoring is healthy but any
invariant has `ok == false` (this is the gray failure), else `ok`. `diverged_at` is the first moment of the current
divergence, `null` otherwise. An invariant that cannot be measured has `ok: null`.

### 4.2 `mystery` — produced by Artham (`core/mystery.py`)
```json
{
  "state": "off | idle | injected | detected | diagnosed | revealed",
  "trial": 3,
  "menu": [{"id": "M-kill-redis", "label": "Crash the queue (Redis)", "fault": "kill", "target": "redis"}],
  "chosen_by": "judge | random | terminal | null",
  "injected_at": null, "detected_at": null, "diagnosed_at": null,
  "detected_by": "kill switch | truth oracle | container state | probes | null",
  "guess": {"fault": "kill", "target": "redis", "confidence": 0.82,
            "top3": [{"fault": "kill", "target": "redis", "confidence": 0.82}],
            "root_cause": "one sentence", "evidence": ["quoted log line or measurement"], "memory_hit": false},
  "answer": {"fault": "kill", "target": "redis"},
  "correct": {"top1": true, "top3": true, "target": true},
  "accuracy": {"trials": 3, "top1": 2, "top3": 3, "target": 3}
}
```
`answer` and `correct` are `null` until `state == "revealed"`. `state` is `idle` only while
`python chaospilot.py mystery --wait` is waiting for a choice; it is `off` otherwise.

### 4.3 `memory` — produced by Dipen
```json
{"last_hit": {"experiment": "E4", "signature_id": "S-redis-kill-worker-exit", "similarity": 0.92,
              "seen_in_run": "auto_20261010_170117", "root_cause": "one sentence", "saved_s": 88.5},
 "signatures": 6}
```
`last_hit` is `null` when the last diagnosis did not come from memory. `saved_s` = time the AI path took last time minus
the time the memory path took now (measured, not estimated).

### 4.4 `fixes` — entries built by Pratham, status updated by Artham's verifier
```json
[{"id": "restart-policy", "title": "Restart crashed containers", "kind": "compose | code_suggestion",
  "for": ["E1", "E2"], "why": "one or two sentences with numbers", "diff": "unified diff text or null",
  "status": "proposed | applied | verified | not_improved | rolled_back",
  "rpn": [{"id": "E2", "before": 270, "after": 30}],
  "rollback_failed": false, "worse": null}]
```
`code_suggestion` entries are always `proposed` (never applied).
`rollback_failed: true` = the fix made a row worse (`worse = {"id": "E3", "before": 630, "after": 700}`) but docker could
not undo it, so it is STILL running: `status` stays `applied`. Show it as a red "rollback failed" badge. Otherwise
`rollback_failed` is `false` and `worse` is `null`. A successful undo is `status: rolled_back`.

### 4.5 `impact` — function by Tejas (`core/report_extras.impact_of`), published by Artham after each experiment
```json
{"experiment": "E6", "votes_lost": 17, "votes_accepted": 40, "outage_s": 20.4, "failed_requests_pct": 42.0,
 "summary": "17 of 40 accepted votes were lost; voting failed for 20 s"}
```

### 4.6 `predictions` — produced by Artham from `results[].prediction_check`
```json
{"items": [{"id": "E1", "predicted": {"probes_affected": ["vote_write"], "data_loss": true, "recovers": false},
            "check": {"probes": true, "recovers": true, "data_loss": false}, "correct": false}],
 "right": 4, "total": 6}
```
An item is `correct` only if no field of `check` is `false`.

### 4.7 `regression` — produced by Tejas
```json
[{"scenario_id": "redis-kill-worker-stays-down", "file": "scenarios/redis-kill-worker-stays-down.json",
  "invariant": "no_stuck_services", "last_status": "pass | fail | never_run", "last_run_at": null}]
```

### 4.8 `plan_ranking` — produced by Artham's Experimenter every turn (brief: "AI ranks and selects experiments with a short reason")
```json
{"turn": 3, "chosen": "pause:db", "reason": "why this experiment now, citing earlier results",
 "types_covered": ["kill", "pause"], "types_required": 3,
 "candidates": [{"id": "kill:db", "type": "kill", "target": "db", "risk_score": 9.0,
                 "predicted_probes": ["result_page"], "tried": true}]}
```
`candidates` is the full ranked list, highest risk first (at most 10). The Experimenter must cover at least
`types_required` (3) different fault types before it may finish or repeat a type.

## 5. Python interfaces (stubs exist; keep these signatures)

```python
# core/truth.py  (Pratham)
class TruthOracle:
    def __init__(self, cfg, prober=None, interval_s=2.0, grace_s=10.0): ...
    def start(self) -> None: ...                 # background thread; never raises
    def stop(self) -> None: ...
    def snapshot(self) -> dict: ...              # shape 4.1
    def window(self, t_start, t_end) -> dict: ... # {"sent","stored","suspected_lost","diverged": bool} for one experiment

# core/patches.py  (Pratham)
def suggest_patches(investigations: dict, results: list) -> list: ...   # list of fix entries, kind "code_suggestion"

# core/heal.py  (Pratham) — existing select_fixes/apply_fixes stay; add:
def fix_entries(fixes: list) -> list: ...      # turn applied catalog fixes into shape 4.4 entries (status "applied")

# agentic/nodes/diagnostician.py  (Dipen) — add:
def diagnose_blind(res: dict, cfg: dict, graph: dict, offline: bool = False) -> dict: ...
#   res is REDACTED: no "name", "steps", "faults_injected", "reason", "hypothesis", "prediction".
#   returns {"fault","target","confidence","top3":[...],"root_cause","evidence":[...],"memory_hit": bool,"seconds": float}
#   fault ∈ {"kill","pause","partition","latency","spike"}; target ∈ config["services"] keys.
def remember_confirmed(res: dict, fault: dict, root_cause: str) -> None: ...  # save a confirmed signature (mystery reveal)

# core/report_extras.py  (Tejas) — add:
def impact_of(result: dict) -> dict: ...       # shape 4.5
def scorecard(results: list, verification: dict, trials: list) -> dict: ...
#   {"predictions": {"right","total"}, "mystery": {"trials","top1","top3","target"},
#    "fixes": {"verified","rolled_back","not_improved"}, "memory_hits": int}
def postmortem(result: dict, investigation: dict, impact: dict) -> str: ...  # markdown section

# core/regression.py  (Tejas)
def export_scenario(result: dict, investigation: dict, run_dir: str) -> str: ...   # returns scenarios/<id>.json path
def replay(path: str, cfg: dict) -> dict: ...  # {"scenario_id","passed": bool,"details": [...]} ; never raises
def list_scenarios() -> list: ...              # shape 4.7

# core/notify.py  (Samridhi)
def notify(kind: str, title: str, text: str, fields: dict | None = None) -> bool: ...
#   kind ∈ {"kill_switch","root_cause","fix_verified","fix_rolled_back","fix_rollback_failed","mystery_reveal","report","gray_failure"}  (8 kinds)
#   reads DISCORD_WEBHOOK_URL from the environment; no URL -> return False silently; never raises; max 1 msg / 2 s.

# core/mystery.py  (Artham)
def menu(cfg) -> list: ...                     # shape 4.2 "menu"
def run_trial(choice_id: str | None, cfg, graph, offline=False, chosen_by="random") -> dict: ...
def wait_loop(cfg, graph, offline=False) -> None: ...   # `python chaospilot.py mystery --wait`
```

## 6. Files on disk

| File | Writer | Reader | Notes |
|---|---|---|---|
| `runs/mystery_request.json` | dashboard server | `core/mystery.py` | `{"choice_id": "M-kill-redis" or "random", "by": "dashboard", "submitted_at"}`, written atomically (tmp + os.replace); mystery deletes it when consumed |
| `runs/mystery_trials.jsonl` | `core/mystery.py` | report, dashboard | one JSON line per trial: `{trial, at, choice_id, chosen_by, answer, guess, correct, seconds_to_detect, seconds_to_diagnose}` |
| `scenarios/*.json` | `core/regression.py` | replay, CI | `{"id","name","steps":[{type,target,delay_s}],"invariants":["no_vote_loss","no_stuck_services","recovers_within_s:20"],"from_run","evidence":[...]}` |
| `sandbox/patches/*.diff` | Pratham (hand-written, reviewed) | `core/patches.py` | unified diffs against the voting-app source; checked with `git apply --check` |
| `runs/<run>/audit.jsonl` | `core/audit.py` (optional) | `chaospilot.py verify-audit` | each line has `prev_hash` and `hash` (sha256) |

Canary votes use ids that start with `canary-`. **Every vote count must exclude them** (`config.json` delivery check is
`SELECT count(*) FROM votes WHERE id NOT LIKE 'canary-%'`), otherwise canaries look like extra delivered votes.

## 7. HTTP endpoints (dashboard/server.py, Samridhi) — same localhost and origin checks as `/stop`

| Method + path | Body | Success | Errors |
|---|---|---|---|
| `POST /mystery` | `{"choice_id": "<menu id>" or "random"}` | `202 {"accepted": true}` and writes `runs/mystery_request.json` | `409 {"error": "not_idle"}` if `mystery.state != "idle"`; `409 {"error": "already_requested"}` if the request file exists; `400 {"error": "unknown_choice"}` |
| `GET /runs` | — | `200 [{"name","started_at","has_report"}]` newest first, only `auto_*` folders | — |
| `GET /runs/<name>/report` | — | `200` markdown text | `404`; `400` if name contains `/`, `\` or `..` |
| `GET /runs/<name>/events` | — | `200 {"lines": [...]}` from `events.log` | same as above |

## 8. Definition of done (for every feature)

1. Works with real Docker on one laptop, and has a fallback when its input is missing.
2. Appears in the dashboard (if it has a live key) or the report.
3. Has a test in `tests/` that runs without Docker or network (monkeypatch `docker`, `requests`, `ask_json`).
4. `python3 tests/test_graph_mock.py`, `python3 tests/test_contract_v5.py` and your own test print ALL CHECKS PASSED.
5. You can explain it in two sentences to a judge.

## 9. Day 2 milestone and deliverable checklist (nothing may be missing at 16:00)

| Brief requirement | How we meet it | Owner | Proof we show |
|---|---|---|---|
| AI planner ranks and selects experiments with a short reason | Experimenter + risk-ranked candidates, `plan_ranking` (4.8) | Artham | Ranked list on dashboard + reason in every event |
| At least 3 failure types | 5 implemented: kill, pause, partition, latency, spike. Coverage rule forces 3 different types per run | Artham (rule), Pratham (live check of all 5) | Golden run with ≥3 types; `docs/day2/FAULT_TYPES.md` |
| Inject with safety limits (error rate, latency, blast radius) | Guard 50% errors / p95 2500 ms / 45 s; Governor ≤2 faults, ≤1 data store; human gate; STOP | Artham | Kill switch firing live; a rejected double kill |
| Observe errors, slowdowns, recovery time | Probes, MTTD/MTTR, Truth Oracle, docker events | Pratham, Tejas | Dashboard + report timings |
| AI findings with root cause | Diagnostician with quoted evidence, blind mystery test | Dipen | Root cause card, mystery accuracy table |
| Recommend fixes | Catalog fixes + code-patch diff | Pratham | Fix cards with diffs |
| Ranked resilience score | FMEA RPN ranking + 0–100 score, before/after | Tejas, Artham | Report + dashboard score |
| Stretch: re-run after fix | Verifier with rollback | Artham | RPN before → after, a rolled-back fix |
| Stretch: live dashboard | Control Room v2 | Samridhi | The demo itself |
| Stretch: combined failures | E6 worker down + Redis crash (needs human approval) | Artham | 17/40 votes lost (re-measure in golden run) |
| Deliverable: code + README | README rewritten as a product README | Tejas | GitHub |
| Deliverable: ≤3-min video | Re-recorded on Day 2 from the golden run | Tejas | `docs/` + link |
| Deliverable: architecture page | `docs/ARCHITECTURE.md` updated to the Day 2 system | Tejas | GitHub |
| Deliverable: findings report | `docs/FINDINGS.md` + generated `report.md` from the golden run | Tejas | GitHub |
| Deliverable: team form | `docs/TEAM_FORM.md` final (not draft) + submitted | Tejas | Submission |
| Out of scope respected | Sandbox-only targets, no shared infra | All | Governor rejection demo |

## 10. The 10-minute talk (draft; owners present their part)

| Min | Part | Who |
|---|---|---|
| 0:00 | Hook: "This app looks healthy. It is losing votes." Truth Oracle shows GRAY FAILURE live | Artham |
| 1:00 | Problem + Bosch link (votes → vehicle crash-sensor events; FMEA is Bosch's own method) | Artham |
| 1:45 | Architecture: 4 AI agents propose, deterministic code approves/kills/scores; human gate | Artham |
| 2:45 | Live: Experimenter plans with a prediction, Governor, kill switch fires | Samridhi drives, Artham narrates |
| 4:00 | Live: judge picks a mystery fault; blind diagnosis; reveal | Dipen |
| 5:30 | Fix: verified RPN drop; bad fix rolled back; worker patch diff | Pratham |
| 6:45 | Memory hit + never-again scenario + CI | Dipen, Tejas |
| 7:30 | Results: accuracy table, predictions scorecard, before/after score, report | Tejas |
| 8:30 | Limits we state honestly + what's next | Tejas |
| 9:00 | Close: "Find, prove, fix, prevent." Questions | Artham |

## Run lifecycle (live_state reset)
`agentic.runtime.start()` calls `LIVE.reset_run(baseline)` before every run. Only `graph`, `thresholds` and `gate_sync`
survive; every other key is dropped and re-published by the new run (`phase`, `events`, `queue`, `probes`, `faulted`,
`guard`, `experiment`, `score`, `findings` restart at empty defaults; `baseline` is re-read from baseline.json).

