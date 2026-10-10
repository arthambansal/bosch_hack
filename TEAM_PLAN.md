# TEAM PLAN (2 days). Read with CONTRACT.md. Artham is the only one who edits CONTRACT.md, config.json, TEAM_PLAN.md.

## Why the plan is shaped this way
Day 1 decides who survives: judges check "app running, dependency map, baseline, one safe failure, kill switch tested, short demo".
So Day 1 = a flawless, boring-but-visible core. Day 2 = the wow: AI planner, 3+ experiments, FMEA + heal loop, what-if, report, video.
Times below assume ~09:30-18:00 each day. Shift them to the real schedule.

## No-overlap rule (everyone has their own files, so merges never conflict)
| Person   | Files (ONLY these) | Day 1 job | Day 2 job |
|----------|--------------------|-----------|-----------|
| Artham   | chaospilot.py, core/{engine,planner,faults,llm,common,fmea,heal}.py, config.json | Run everything on a real laptop, fix engine bugs, merge hourly, lead the Day-1 demo | Real AI planner online, wire `ask` + breakpoint, final integration, demo captain |
| Pratham  | sandbox/*, core/{discover,probes}.py, TESTLOG.md, targets/* | Verify `up`, `map`, `baseline`; test ALL 5 faults + kill switch one by one; log exact numbers | Second target app in `targets/` (generality proof), test `heal` and the combined failure E6 |
| Samridhi | dashboard/server.py, dashboard/index.html | Dashboard v1: dependency graph (red when faulted), live latency/error chart, event log, kill-switch banner | FMEA table, before/after RPN bars, resilience gauge, findings list, SILENT DATA LOSS banner, optional what-if box |
| Dipen    | core/report.py, core/ask.py | Rule-based report.py (no AI): scoring formula + FMEA table into report.md from results.json. Test on synthetic data | LLM post-mortem prompt (root cause + fix per row), `--compare` before/after, `ask.py` natural-language what-if |
| Tejas    | README.md, docs/*, core/mermaid.py | README (setup + run), `core/mermaid.py` (dependencies.json -> Mermaid diagram in docs/), architecture draft, record Day-1 demo | One-page architecture, findings report from REAL output, final 3-min video, team form, submission, final README check |

New-file contracts (so the pieces plug in without talking):
- `core/mermaid.py`: `def to_mermaid(graph: dict) -> str` (graph = dependencies.json). `python core/mermaid.py` writes docs/dependency_map.md.
- `core/ask.py` (Dipen): `def parse_whatif(text, cfg, graph, baseline, offline=False) -> dict | None`. Returns ONE experiment in plan.json format (see CONTRACT), built ONLY from `planner.candidates()` ids; the LLM may pick candidates and delays, never invent targets. Return None if the request can't be mapped. Artham adds `python chaospilot.py ask "redis dies while 30 users vote"`.
- `targets/<app>/` (Pratham): `docker-compose.yml` + `config.json` in the same schema as the root config.json. `python chaospilot.py` gets `--config targets/<app>/config.json` (Artham adds).

## Git rules
Branch = your name. `git pull --rebase origin main` before each push. Push every 30-45 min: `git push -u origin yourname`. Only Artham merges to main (on the hour). Never commit API keys. Bug in someone's file: send them the exact error text, do not edit it.

---
## DAY 1 (the survival day)
Gate = ALL of: sandbox up, dependency map generated, baseline captured, one failure injected with visible impact, kill switch fires AND restores, 60-90 s demo works 3 times in a row.

| Time  | Who | What | Done when |
|-------|-----|------|-----------|
| 11:45 | Everyone | clone, branch, `pip install requests`, `python chaospilot.py up`, vote at localhost:8080 | screenshot in group chat |
| 12:30 | Pratham -> Artham | `map`, `baseline`, `plan`, `run --only E1` outputs + errors in TESTLOG.md | Artham has real output to debug against |
| 12:30 | Artham -> Samridhi, Dipen | real `runs/live_state.json` and `results.json` samples | they stop using fake data |
| 14:00 | Artham | all 5 faults tested, E6 combined tested; engine bugs fixed | `python chaospilot.py demo` runs end to end |
| 14:30 | Samridhi, Dipen, Tejas | push first versions; Artham merges | dashboard shows a live run; report.md produced |
| 15:30 | Everyone | FEATURE FREEZE for Day 1. Rehearse demo twice, other laptop too | demo works 3x in a row |
| 16:30 | Tejas + Pratham | record Day-1 demo video (backup) | video file saved |
| 17:00 | Tejas | Day-1 submission/checkpoint form if asked | submitted |

DAY-1 DEMO SCRIPT (90 s, rehearse it): 1) `up` + show app (10s). 2) `map`: show dependency edges + diagram (15s). 3) `baseline`: show normal numbers (10s). 4) `run --only E1` (kill redis) with dashboard open: errors appear, guard counts 1/3, 2/3, 3/3, KILL SWITCH, auto-restore, "recovered in X s" (40s). 5) say: "FMEA scores it, tomorrow the AI plans, combines and heals" (15s).
PLAN B (insurance, 10 min to set up, Pratham): keep the earlier simple `chaos_inject.py` + `safety_guard.py` working on a second laptop. If the engine breaks 10 minutes before the demo, run those.

---
## DAY 2 (the winning day), in priority order (cut from the BOTTOM if behind)
1. AI planner online (Artham, free Groq/Claude key): ranked experiments with reasons. Run 3+ fault types + the combined E6.
2. FMEA + `heal` loop: break -> RPN table -> fix -> re-run -> RPN drops (Artham runs, Pratham verifies, Samridhi shows it).
3. AI post-mortem (Dipen): ranked findings, root cause, fix per row, numbers quoted from results.
4. Dashboard final (Samridhi): FMEA, before/after, score, silent-data-loss banner.
5. Deliverables (Tejas): architecture page, findings report from real output, README clean-run test, team form.
6. STRETCH A: `ask` what-if. Judges type a scenario live; AI maps it to a validated experiment (Dipen + Artham).
7. STRETCH B: second target app proves the tool is app-agnostic (Pratham).
8. STRETCH C: breaking-point finder: ramp the traffic spike until errors cross the threshold -> "capacity limit = N req/s" (Artham, only if everything above is done).

| Time (Day 2) | Milestone |
|--------------|-----------|
| 09:30 | Fresh clone + `up` on everyone's laptop; Artham sets the LLM key |
| 11:30 | Planner + FMEA + dashboard v2 working together on one laptop |
| 13:00 | Heal loop proven with real numbers; post-mortem generated |
| 14:30 | FEATURE FREEZE. Stretch items that are not working get cut, no exceptions |
| 15:00 | Clean run from scratch on a second laptop (Pratham). Record 3-min video (Tejas leads, Artham drives) |
| 16:30 | Submit; everyone opens all 5 deliverables to verify. Aim to finish 30 min early |

3-MINUTE VIDEO: 0:00 problem + one-line pitch | 0:20 map + prediction | 0:50 live failure + kill switch on dashboard | 1:30 silent data loss -> FMEA table | 2:00 heal + RPN drop | 2:30 what-if or second app (if working) | 2:50 close.
