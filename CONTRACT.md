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
  `phase("idle"|"baseline"|"running"|"ran"|"reporting"|"healing"|"healed"), events[{t,kind,msg}] (last 60; kind=info|inject|guard|restore|ai|ok|warn),
   queue[{id,name,reason,status(planned|running|completed|aborted|refused),score,root_cause}], probes{name:{series[[sec_ago,latency_ms,ok]],n,ok,error_rate,p50_ms,p95_ms}},
   faulted[{target,type}], guard{ticks,reasons[],tripped,elapsed}, experiment{...plan entry...}|null, thresholds{max_error_rate,max_p95_ms,breach_ticks},
   graph{...dependencies.json...}, baseline{...}, score{overall,grade,after}|null, findings[...]|null,
   fmea[{id,failure_mode,effect,S,O,D,rpn,action_priority,detection_note,evidence}], fmea_compare[{id,failure_mode,rpn_before,rpn_after,reduction_pct}],
   agent_active, approval_request, threat_model`
- Agent thoughts are events with kind `ai` whose `msg` starts with `[AgentName]`, for example `[Cartographer]`, `[Experimenter]`, `[Governor]`, `[Diagnostician]`, `[Remediator]`, `[Reporter]`.
- Human approval: the Governor writes `approval_request` to live_state and waits for `runs/approval.json` = `{"approved": true|false}`. Default is deny. The dashboard (POST /approve) and the Discord bot both write this file.
- S, O, D and RPN are always computed by code in core/fmea.py. The AI never sets them.
- The resilience score is deterministic (agentic/nodes/reporter.py). The AI only explains it.

## Shared agent state
`agentic/state.py` is the single contract between agent nodes (LangGraph state). Only Artham edits it.
New data between agents is added as a new key there, never by importing another person's module.

## CLI (Artham)
`python3 chaospilot.py <up|map|baseline|plan|run|agent|autopilot|graph|report|heal|dashboard|panic|demo>`
Flags: `--offline`, `--only E1,E2`, `--compare <run_dir>`, `--goal "..."`, `--approve`, `--no-heal`, `--max N`
