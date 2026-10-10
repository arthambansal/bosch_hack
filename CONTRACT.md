# CHAOSPILOT DATA CONTRACT (v3)

**Who owns which file, and the timeline, are in `docs/PROJECT_BLUEPRINT.md` Section 20.** This file only lists the data
formats that flow between modules. Never change a format without telling Artham first.

Rules: (1) you only edit files you own; (2) you talk to other modules only through the formats below and `agentic/state.py`;
(3) a bug in someone else's file goes to the owner with the exact error text; (4) branch = your name, push small and often;
(5) before every push, `python3 tests/test_graph_mock.py` must print ALL CHECKS PASSED.

## Files that flow between modules (all inside the repo root)
- `dependencies.json`  written by core/discover.py. Keys: `services{name:{container,role,stateful,depends_on[],used_by[],level,blast_radius[],listen_ports[]}}`, `edges[{from,to,evidence[]}]`, `data_flows[str]`
- `baseline.json`      `{probes:{name:{n,ok,error_rate,p50_ms,p95_ms}}, delivery:{sent,delivered}}`
- `plan.json`          `{source, experiments:[{id,name,steps[{type,target,delay_s}],reason,hypothesis,risk_score,predicted_probes[]}]}`
- `runs/run_*/results.json`  list of experiment results:
  `{id,name,steps,reason,hypothesis,predicted_probes[],status("completed"|"aborted"|"refused"),abort_reason,fault_window_s,recovery_s(null=never),probes:{name:{n,ok,error_rate,p50_ms,p95_ms,time_to_first_error_s}},guard_log[],delivery:{sent,delivered,lost},stuck_services[],stuck_details{},prediction,prediction_check}`
- `runs/live_state.json` rewritten ~2x/second while anything runs. The dashboard reads it via http://localhost:8000/state. Keys:
  `phase("idle"|"baseline"|"running"|"ran"|"stopped"|"reporting"|"healing"|"healed"), events[{t,kind,msg}] (last 60; kind=info|inject|guard|restore|ai|ok|warn),
   queue[{id,name,reason,status(planned|running|completed|aborted|refused),score,root_cause}], probes{name:{series[[sec_ago,latency_ms,ok]],n,ok,error_rate,p50_ms,p95_ms}},
   faulted[{target,type}], guard{ticks,reasons[],tripped,elapsed}, experiment{...plan entry...}|null, thresholds{max_error_rate,max_p95_ms,breach_ticks},
   graph{...dependencies.json...}, baseline{...}, score{overall,grade,after}|null, findings[...]|null,
   fmea[{id,failure_mode,effect,S,O,D,rpn,action_priority,detection_note,evidence}], fmea_compare[{id,failure_mode,rpn_before,rpn_after,reduction_pct}],
   agent_active, approval_request, threat_model`
- Agent thoughts are events with kind `ai` whose `msg` starts with `[AgentName]`, for example `[Cartographer]`, `[Experimenter]`, `[Governor]`, `[Diagnostician]`, `[Remediator]`, `[Reporter]`.
- Human approval and STOP (v4, gate token + expiry). Implemented in `agentic/gate.py`.
  1. When a high-risk experiment needs sign-off the orchestrator publishes in live_state:
     `approval_request = {gate_id, id, name, question, reason, steps[], created_at, expires_at, timeout_s}`.
     `gate_id` is a fresh random token for EVERY question (never reused, even for the same experiment id).
     It is published only AFTER the old runs/approval.json has been removed, and nothing is deleted afterwards.
  2. The dashboard (`POST /approve`) and Discord send `{gate_id, approved: true|false}`. The SERVER must check that
     `gate_id == live_state.approval_request.gate_id` and `now < expires_at`; otherwise answer HTTP 409
     `{"error": "no_pending" | "stale" | "expired"}` and write nothing. If valid, write `runs/approval.json` ATOMICALLY
     (write `approval.json.tmp`, then `os.replace`): `{"gate_id", "approved": true|false, "by": "dashboard"|"discord", "submitted_at"}`.
  3. The orchestrator accepts ONLY a file whose gate_id matches the open gate. The first valid decision wins, the file is
     removed, a second submit for the same gate is rejected by the server (no pending gate) and ignored by the orchestrator.
     (Legacy: a file WITHOUT gate_id is accepted only if it is newer than the request. Deprecated.)
  4. After the answer, live_state: `approval_request = null` and `approval_result = {gate_id, answer: "approved"|"denied",
     source: "dashboard"|"terminal"|"timeout"|"stop", at}`. No answer before `expires_at` = denied. A STOP = denied at once.
  5. `POST /stop` creates the `STOP` file in the repo root. The orchestrator checks it before every graph node, before every
     fault injection, between verification experiments and while waiting for approval. Then it restores everything and writes
     a partial report.
  6. Run state for the UI: `run_status` = "running" | "stopping" | "stopped" | "completed"; `phase` = also "stopped";
     `cleanup = {done, stopped, at}` (set when every fault is undone and traffic stopped); `report_path` (null until a report
     exists, including the partial report after STOP).
- S, O, D and RPN are always computed by code in core/fmea.py. The AI never sets them.
- The resilience score is deterministic (agentic/nodes/reporter.py). The AI only explains it.

## Shared agent state
`agentic/state.py` is the single contract between agent nodes (LangGraph state). Only Artham edits it.
New data between agents is added as a new key there, never by importing another person's module.

## CLI (Artham)
`python3 chaospilot.py <up|map|baseline|plan|run|agent|autopilot|graph|report|heal|dashboard|panic|demo>`
Flags: `--offline`, `--only E1,E2`, `--compare <run_dir>`, `--goal "..."`, `--approve`, `--no-heal`, `--max N`
