# CHAOSPILOT TEAM CONTRACT (v1, frozen at 11:00 - changes only via Artham)

Rule 1: you only edit files you OWN. Rule 2: you only talk to others through the file formats below.
Rule 3: if a format must change, tell Artham first. Rule 4: commit small, push every 30 min, branch = your name.

## Ownership
| Person  | Role                         | Owns (only edits these)                                          |
|---------|------------------------------|------------------------------------------------------------------|
| Artham  | Lead / integrator            | chaospilot.py, core/engine.py, core/planner.py, core/faults.py, core/llm.py, core/common.py |
| Pratham | Sandbox + reliability tester | sandbox/*, core/discover.py, core/probes.py, TESTLOG.md, run_demo.sh |
| Samridhi| Live dashboard               | dashboard/index.html (single file, no build step)                |
| Dipen   | Scoring + AI analysis        | core/report.py (+ the LLM prompts inside it)                     |
| Tejas   | Docs + submission            | README.md, docs/*, findings report, video, team form             |

Bugs in someone else's file: message the owner with the exact error text. Do not fix it yourself.

## Files that flow between modules (all inside bosch_hack/)
- `dependencies.json`  written by discover.py. Keys: `services{name:{container,role,stateful,depends_on[],used_by[],level,blast_radius[],listen_ports[]}}`, `edges[{from,to,evidence[]}]`, `data_flows[str]`
- `baseline.json`      `{probes:{name:{n,ok,error_rate,p50_ms,p95_ms}}, delivery:{sent,delivered}}`
- `plan.json`          `{source, experiments:[{id,name,steps[{type,target,delay_s}],reason,hypothesis,risk_score,predicted_probes[]}]}`
- `runs/run_*/results.json`  list of experiment results:
  `{id,name,steps,reason,hypothesis,predicted_probes[],status("completed"|"aborted"|"refused"),abort_reason,fault_window_s,recovery_s(null=never),probes:{name:{n,ok,error_rate,p50_ms,p95_ms,time_to_first_error_s}},guard_log[],delivery:{sent,delivered,lost}}`
- `runs/live_state.json` rewritten ~2x/second while anything runs. Dashboard reads it via http://localhost:8000/state. Keys:
  `phase("idle"|"baseline"|"running"|"ran"|"reporting"), events[{t,kind,msg}] (last 60; kind=info|inject|guard|restore|ai|ok|warn),
   queue[{id,name,reason,status(planned|running|completed|aborted|refused),score}], probes{name:{series[[sec_ago,latency_ms,ok]],n,ok,error_rate,p50_ms,p95_ms}},
   faulted[{target,type}], guard{ticks,reasons[],tripped,elapsed}, experiment{...plan entry...}|null, thresholds{max_error_rate,max_p95_ms,breach_ticks},
   graph{...dependencies.json...}, baseline{...}, score{overall,grade,per_experiment{id:score}}|null, findings[...]|null`

## core/report.py - Dipen implements EXACTLY these functions
```python
def score_experiment(result: dict, baseline: dict) -> dict:
    # returns {"id","score":0-100,"severity":"critical|high|medium|low|pass","penalties":{name:points}}
def build_report(run_dir: str, compare_dir: str | None = None, offline: bool = False) -> dict:
    # reads run_dir/results.json + baseline.json + dependencies.json
    # writes run_dir/report.json and run_dir/report.md; calls LIVE.set(score=..., findings=...)
    # returns the report dict. compare_dir = an earlier run -> add before/after table (stretch goal)
```
Imports available: `from .common import LIVE, load_json, save_json, DEPS_FILE`, `from .llm import ask_json`
(`ask_json(kind, system, user, offline=False)` -> `(dict|None, source)`; it handles API errors/caching, so call it and ALWAYS write a rule-based fallback for when it returns None).

Scoring (deterministic, no AI - AI only explains): start 100, subtract
- availability: min(40, 40 * max error_rate over all probes in result)
- recovery: 30 if recovery_s is null, else min(20, 1.5 * recovery_s)
- data loss: 0 if lost==0/None, else min(30, 10 + lost)
- blast radius: 10 if any probe NOT in predicted_probes has error_rate >= 0.5
- kill switch: 10 if status == "aborted"
floor 0. Severity: critical = data loss or never recovered; high = aborted or recovery_s>15; medium = score<70; low = score<90; else pass.
Overall = average of scores weighted by risk_score of the experiment. Grade: A>=90, B>=80, C>=70, D>=60, else F.

LLM report call (one call, kind="report"): input = results + baseline + dependency map (compact JSON).
Required output JSON: `{"summary": str, "findings":[{"experiment_id","severity","weakness","evidence"(must quote numbers from results),"root_cause","fix","fix_snippet"(compose/code, optional)}], "priority_order":[experiment_id...]}`.
Prompt must say: use ONLY numbers present in the input, rank by severity, one concrete fix per finding, no invented services.
Overall resilience score is ours (deterministic). The AI never sets it.

## Dashboard (Samridhi): one file dashboard/index.html, plain JS, no libraries needed (canvas/SVG ok).
Panels: (1) dependency graph coloured by status (red = in `faulted`, amber = predicted blast radius of faulted), (2) latency+error chart per probe from `probes.*.series`,
(3) experiment queue with status + AI reason, (4) event log colour-coded by kind, (5) guard bar showing ticks/breach_ticks and a big KILL SWITCH banner when `guard.tripped`,
(6) resilience score gauge + findings list when `score`/`findings` are non-null. Poll `/state` every 500 ms. Must work offline (no CDN).
Test without the backend: save any sample of live_state.json (Artham gives one at 11:30) and use a `?mock=1` mode.

## CLI (Artham): `python chaospilot.py <up|map|baseline|plan|run|report|dashboard|panic|demo>`; flags `--offline`, `--only E1,E2`, `--compare <run_dir>`

## Checkpoints (who sends what to whom)
| Time  | Who -> whom                                   | What                                                         |
|-------|-----------------------------------------------|--------------------------------------------------------------|
| 11:15 | Everyone -> group                              | "docker compose up works on my laptop" (screenshot) or exact error |
| 11:30 | Pratham -> Artham                              | TESTLOG.md: results of `map`, `baseline`, one `run --only E1` on his machine |
| 11:30 | Artham -> Samridhi, Dipen                      | sample live_state.json + sample results.json                 |
| 13:00 | Samridhi, Dipen -> Artham                      | first working version pushed to their branch                 |
| 13:30 | Artham                                         | merges all, full `demo` run on one laptop                    |
| 15:00 | FEATURE FREEZE                                 | only bug fixes after this                                    |
| 15:30 | Tejas -> everyone                              | final README + architecture page for review                  |
| 16:00 | Clean run from scratch on a SECOND laptop      | Pratham runs it, records video with Tejas                    |
| 16:45 | Tejas                                          | submit form; everyone verifies all 5 deliverables open       |

---
# ADDENDUM v1.1 (11:30) - the differentiator: "Automotive-grade FMEA + closed-loop healing"
Pitch line: "ChaosPilot turns chaos experiments into the FMEA table Bosch engineers already use, then fixes the top
risks and PROVES the RPN dropped." New files (Artham owns): core/fmea.py, core/heal.py, sandbox/fixes/*.yml, `python chaospilot.py heal`.
Nothing above changed. Additions only:
- live_state.json gains `fmea[{id,failure_mode,effect,S,O,D,rpn,action_priority,detection_note,evidence}]` (updates after each experiment),
  `fmea_compare[{id,failure_mode,rpn_before,rpn_after,reduction_pct}]` (after `heal`), phase value "healing"|"healed".
- Dipen: `build_report` must `from .fmea import build_fmea, compare_fmea`, put the FMEA table FIRST in report.md/report.json["fmea"],
  and send the FMEA rows (not just raw results) to the LLM. Per row the LLM adds `root_cause`, `fix`, `fix_snippet`. S, O, D, RPN are NEVER set by the LLM.
  If compare_dir is given, add the before/after RPN table (compare_fmea).
- Samridhi: add panel 7 = FMEA table (colour by action_priority: High red, Medium amber, Low green) and, when `fmea_compare` exists,
  a before->after RPN bar per experiment with the % reduction. Banner "SILENT DATA LOSS" when any row has evidence.lost_votes > 0.
- Pratham: test `up --fix restart-policy.yml`, `up --fix redis-durable.yml`, then `heal`. Check that E6 (worker down, then redis crash) shows lost votes BEFORE and 0 AFTER; put the numbers in TESTLOG.md.
- Tejas: pitch = 1 slide explaining S/O/D/RPN in Bosch language; findings report = the FMEA table + before/after. Read core/fmea.py docstring; tell Artham if the O-priors look wrong.
- Pratham also: sandbox now pins redis:7.2-alpine (last BSD-licensed Redis), already edited.
Demo story (3 min): map -> predicted blast radius -> E6 combined failure -> kill switch + silent data loss found -> FMEA S10/D10 -> `heal` -> same experiment, 0 lost, RPN 600 -> ~90.
