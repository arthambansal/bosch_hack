# HOW TO USE: open your own GPT chat. Paste (1) the files listed under "ATTACH", then (2) your prompt. Do not let GPT change file formats.

Shared opening line for everyone (paste first):
"We are a 5-person team in the Bosch hackathon 'AI-Driven Chaos Engineering'. Our tool ChaosPilot breaks a sample Docker app on purpose with a kill switch, then analyses it. I own ONLY the files listed below. Never change the file formats in CONTRACT.md. Keep code simple, commented, beginner friendly, Python standard library + requests only (dashboard: plain HTML/JS, no CDN, no build step). Ask me before assuming anything."

---
## PRATHAM  (sandbox + tester)
ATTACH: CONTRACT.md, TEAM_PLAN.md, config.json, sandbox/docker-compose.yml, core/discover.py, core/probes.py, core/faults.py
PROMPT:
I am Pratham. I own sandbox/*, core/discover.py, core/probes.py, TESTLOG.md, targets/*.
Day 1 job: I am the reliability tester. Walk me step by step through running `python chaospilot.py up`, `map`, `baseline`, `plan`, then `run --only E1`. For every failure I paste, find the root cause in the attached code and give me the exact fix for MY files only; for bugs in files I do not own, write a short bug report (command, exact error, suspected cause) I can send to Artham. Then help me test each fault type one at a time (kill, pause, partition, latency, spike) on each service, and record in TESTLOG.md: command, what happened, numbers, pass/fail. Also keep a Plan B: tell me how to verify the simple scripts chaos_inject.py and safety_guard.py still work on a second laptop.
Day 2 job: add a second target app under targets/<app>/ (docker-compose.yml + config.json in the same schema as config.json, probes and delivery_check adapted). Suggest 2 open-source multi-service Docker Compose apps that run on Apple Silicon and have a clear queue/database, and let me choose.

---
## SAMRIDHI  (dashboard)
ATTACH: CONTRACT.md (especially the live_state.json section and ADDENDUM v1.1), TEAM_PLAN.md, dashboard/server.py, a sample runs/live_state.json (ask Artham)
PROMPT:
I am Samridhi. I own dashboard/index.html and dashboard/server.py only.
Build ONE self-contained dashboard/index.html (plain HTML/CSS/JS, no CDN, works offline) that polls http://localhost:8000/state every 500 ms and renders live_state.json exactly as described in CONTRACT.md. Day 1 panels: (1) dependency graph from `graph.services` and `graph.edges`, nodes laid out by `level`, node red when in `faulted`, amber when in the blast radius of a faulted node; (2) per-probe latency + error chart from `probes.<name>.series` ([sec_ago, latency_ms, ok]) drawn on canvas/SVG, with threshold lines from `thresholds`; (3) event log, coloured by `kind`; (4) guard bar showing guard.ticks / thresholds.breach_ticks and a large red KILL SWITCH banner when guard.tripped; (5) experiment queue with status. Add a `?mock=1` mode that animates fake data so I can work without the backend. Make it look like a professional SRE control room: dark theme, readable on a projector, large fonts.
Day 2 I will ask you to add: FMEA table (colour by action_priority), before/after RPN bars from fmea_compare, resilience score gauge, findings list, and a SILENT DATA LOSS banner when any fmea row has evidence.lost_votes > 0.
Start with Day 1. Give me the complete file.

---
## DIPEN  (scoring + AI analysis)
ATTACH: CONTRACT.md (read the report.py section and ADDENDUM v1.1), TEAM_PLAN.md, core/fmea.py, core/llm.py, core/common.py, a sample results.json (ask Artham)
PROMPT:
I am Dipen. I own core/report.py and core/ask.py only.
Day 1: write core/report.py with exactly the signatures in CONTRACT.md: score_experiment(result, baseline) and build_report(run_dir, compare_dir=None, offline=False). The scoring formula is in CONTRACT.md; implement it exactly and deterministically. build_report must also call build_fmea from core/fmea.py, write run_dir/report.json and run_dir/report.md (FMEA table first, then per-experiment scores, then a rule-based findings list with a fix suggestion per finding, no AI needed yet), and call LIVE.set(score=..., findings=...). Test it with synthetic data first, then with real results.json from Artham.
Day 2: add the LLM post-mortem inside build_report using ask_json(kind="report", ...): input = FMEA rows + results + baseline + compact dependency map; the model returns JSON {summary, findings[{experiment_id, severity, weakness, evidence, root_cause, fix, fix_snippet}], priority_order[]}. The prompt must say: use ONLY numbers in the input, rank by severity, one concrete fix per finding, never invent services, never set S/O/D/RPN. Keep the rule-based fallback for when ask_json returns None. Add --compare support (before/after RPN table via compare_fmea).
Day 2 stretch: write core/ask.py with parse_whatif(text, cfg, graph, baseline, offline=False) -> one experiment dict in plan.json format, built ONLY from candidates() in core/planner.py (the LLM picks candidate ids and delays; validate everything; return None if it cannot map).

---
## TEJAS  (docs, diagram, demo, submission)
ATTACH: CONTRACT.md, TEAM_PLAN.md, hackathon_details_and_guidelines.md (the brief), sandbox/docker-compose.yml, dependencies.json (after `map` runs)
PROMPT:
I am Tejas. I own README.md, docs/*, core/mermaid.py only.
Day 1: (a) write README.md covering: what ChaosPilot is, the sample app + repo link + license, prerequisites (Docker Desktop, Python 3.10+, pip install requests), exact run steps (`up`, `map`, `baseline`, `plan`, `run`, `heal`, `dashboard`), safety controls (kill switch thresholds, sandbox-only refusal, STOP file, panic command). (b) write core/mermaid.py with `to_mermaid(graph: dict) -> str` turning dependencies.json (services, edges) into a Mermaid flowchart, and running `python core/mermaid.py` writes docs/dependency_map.md. (c) draft the architecture overview: components, how the AI makes decisions (planner proposes, code validates, the AI never sets scores or runs commands), safety controls.
Day 2: finalize the one-page architecture, the findings report from REAL output (weaknesses ranked, with fixes), the 3-minute video script (use the timings in TEAM_PLAN.md), and the team form (list: Docker Example Voting App, Redis 7.2, PostgreSQL 15, nicolaka/netshoot, Python requests; AI models: Claude, ChatGPT, plus the runtime API model Artham names).
Keep everything short, specific and honest: never claim a feature that does not work in the demo.
