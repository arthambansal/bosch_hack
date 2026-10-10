# ChaosPilot architecture

ChaosPilot runs controlled resilience experiments against an isolated Docker
Example Voting App. The pipeline is a guarded loop: propose, approve, inject,
observe, explain, repair, verify, report, and replay.

## Components and decisions

| Component | Decision it makes |
|---|---|
| **Cartographer** | Reads bounded, read-only source files and proposes weaknesses with file/line/function citations. It keeps hypotheses open and uses the rule fallback when AI output is unavailable or invalid. |
| **Experimenter** | Ranks hypotheses and chooses a fault, target, prediction, and expected invariants. |
| **Governor** | Accepts or rejects the proposed experiment against configuration, sandbox labels, fault-count limits, stateful-service limits, and known invariants. |
| **Human approval gate** | Requires explicit approval for destructive data-store or combined faults. A denial blocks injection. |
| **Engine / Executor** | Applies the approved fault in the sandbox and records the timeline. |
| **Guard and kill switch** | Watches error rate, latency, blast radius, duration, and STOP. A breach halts or restores the active fault. |
| **Observer and Truth Oracle** | Probes HTTP behavior and compares canary votes accepted by the API with votes delivered to the result store. |
| **Diagnostician** | Explains the observed failure from results, source context, and remembered signatures without inventing evidence. |
| **Remediator** | Selects a catalogued fix or proposes a patch; suggestions are separate from applied code. |
| **Verifier** | Repeats the experiment after a fix, compares measured RPN, and records pass/fail plus rollback status. |
| **Reporter** | Computes FMEA, resilience score, impact, MTTD/MTTR when measurable, executive summary, fault tree, heatmap, and findings. |
| **Regression replay** | Exports only confirmed measured failures and checks their invariants on later runs. |

## How AI makes decisions

When configured, the LLM suggests source-grounded hypotheses and helps rank or
explain candidates. Every AI result is validated for schema, allowed tools, and
real source citations. Invalid, uncited, or unavailable output falls back to
deterministic rules. The LLM never computes FMEA or resilience numbers, bypasses
Governor policy, operates outside the sandbox, or applies code by itself.
Measurements, approvals, scores, and replay verdicts come from program logic.

## Safety controls

- **Sandbox-only:** targets must be configured services carrying the expected
  Compose project label; source tools are read-only and bounded.
- **Governor:** allows at most two faults and at most one stateful data store,
  rejects unknown targets/invariants, and enforces duration and blast-radius
  limits before Engine construction.
- **Guard:** monitors rolling error rate, p95 latency, service health, and data
  delivery. Three consecutive threshold breaches trigger restoration.
- **Kill switch and STOP:** a STOP file or dashboard action halts the run and
  restores active faults, including on replay failure.
- **Human gate:** combined and data-store disruptions require fresh, scoped
  approval; stale, missing, or denied approvals cannot authorize injection.

Graph state contains interfaces and evidence references only. Runtime objects and
credentials stay outside serialized state, and API keys remain environment
variables. Mock tests validate contracts; live claims require preserved artifacts.
