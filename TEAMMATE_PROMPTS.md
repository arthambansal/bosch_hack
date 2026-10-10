# HOW EACH TEAMMATE STARTS (10 minutes)

1. `git pull origin main`, then `pip3 install -r requirements.txt`, then `python3 tests/test_graph_mock.py` (must say ALL CHECKS PASSED).
2. Upload `docs/PROJECT_BLUEPRINT.md` to your LLM, plus the files listed for you below.
3. Paste: "I am <name>. My role is in Section 20.2 of the blueprint. Help me build my part exactly as specified. Never change data formats in Sections 8 and 9 or the keys in agentic/state.py. Every agent node keeps its rule-based fallback. Tools stay read-only. I only edit the files I own. Before I push, tests/test_graph_mock.py must pass. Give me complete, commented files."
4. Then paste your first task below.

The split (everyone has one AI "brain" plus hands-on parts):

| Person | Brain | Hands-on |
|---|---|---|
| Artham | Experimenter agent | Orchestrator, schemas, Safety Governor, Executor and faults, integration, demo |
| Pratham | Remediator agent | Observer (canary, events, logs), sandbox and fixes |
| Dipen | Diagnostician agent | Knowledge Store, signatures, mystery-fault test |
| Samridhi | Briefing and approvals | Control Room dashboard, Discord alerts |
| Tejas | Cartographer agent | Reporter extras, README, video, architecture page, team form |

No shared files: every agent lives only in its own file under `agentic/nodes/`. If you need a change in someone else's file, message them with the exact request.

## Artham (lead): attach agentic/graph.py, agentic/state.py, agentic/nodes/experimenter.py, agentic/nodes/governor.py, agentic/nodes/execute.py, core/engine.py, core/faults.py
First task: run `python3 chaospilot.py autopilot --max 3 --no-heal` on real Docker with the Groq key set; fix anything that breaks. Next: add agentic/schemas.py (Pydantic models for the Section 8.2 messages). Then upgrade the Experimenter (hypothesis-driven, predict-then-check, uses the Knowledge Store once Dipen's module exists), add packet-loss and CPU-throttle faults to core/faults.py, and add the Governor's LLM reviewer.

## Pratham (Remediator + Observer): attach agentic/nodes/remediator.py, core/heal.py, core/probes.py, core/engine.py, core/discover.py, config.json, sandbox/docker-compose.yml, sandbox/fixes/*
First task: create core/observer.py with (a) the canary tracer from blueprint 7.2 (cookie voter_id=canary-<n>, then check the row in Postgres; report delivery ratio and lag), (b) a docker-events watcher recording die/start with timestamps, (c) log-template mining (mask numbers, hex, IPs) with a healthy template set, (d) the anomaly rules in 7.1. Expose observer.summary(t_start, t_end) returning the "Observation summary" JSON of 8.2. Next: apply the random-vote patch in core/probes.py (`data=({"vote": random.choice("ab")} ...)`) so results are not 100% Cats. Then Remediator upgrade: draft a compose override (only keys restart, healthcheck, command for redis, deploy.resources), validate against the whitelist, save to sandbox/fixes/generated/, apply, and let the verifier decide; verify E1 and E6 before/after numbers into TESTLOG.md.

## Dipen (Diagnostician + Knowledge): attach agentic/nodes/diagnostician.py, core/tools.py, core/agentkit.py, a real results.json
First task: create core/knowledge.py (SQLite tables from 9.2) and core/signatures.py (turn a result into the FailureSignature of 8.2; similarity = cosine or Jaccard over features). Then upgrade the Diagnostician to follow the six steps of Section 11 (topology localisation + signature retrieval + mechanism evidence, then LLM differential, then confidence rules). Day 2: core/mystery.py, where a hidden fault is chosen, injected, and the Diagnostician's answer is scored (accuracy over at least 8 trials).

## Samridhi (Control Room + Briefing/Approvals): attach dashboard/server.py, agentic/state.py, a real runs/live_state.json, output of `python3 chaospilot.py graph`
First task: dashboard/index.html with the Day-1 panels from Section 18 (agent graph with active agent, reasoning feed, dependency map, kill-switch bar, approval card with POST /approve, STOP button with POST /stop). Then core/notify.py: Discord webhook alerts (URL from env DISCORD_WEBHOOK_URL, never committed) for kill switch fired, root cause found, fix verified, final report card. Then core/briefing.py: turns the event feed into one-line plain-language alerts (LLM through core/llm.ask_json, template fallback), and core/approvals.py: Discord approve/deny that writes runs/approval.json (default deny).

## Tejas (Cartographer + Reporter + deliverables): attach agentic/nodes/cartographer.py, core/tools.py, core/agentkit.py, agentic/nodes/reporter.py
First task: `git clone https://github.com/dockersamples/example-voting-app sandbox/app-src`; create core/code_tools.py (list_files, read_file, grep, all confined to sandbox/app-src); give them to the Cartographer and make it output the Hypothesis JSON of 8.2. Success = it finds W1 (Section 3.3) by itself, citing file and function. Then add MTTD/MTTR and an AI executive summary to the Reporter (core/report_extras.py), then the fault tree and heatmap. Own the five deliverables: README, architecture one-pager, findings report from the real run, 3-minute video, team form.
