"""THE CONTRACT. Every agent node reads and writes ONLY these keys. Change only via Artham.

LangGraph passes this dict between nodes. A node returns a dict with the keys it updates.
Everything here must be plain JSON data (no objects), so runs can be checkpointed and replayed.
"""
from typing import Optional, TypedDict


class ChaosState(TypedDict, total=False):
    # ---- inputs (set by the runner) ----
    goal: str                    # optional user what-if, e.g. "what if redis dies during a traffic spike?" ("" = free run)
    graph: dict                  # dependencies.json (services, edges, data_flows)
    baseline: dict               # baseline.json
    offline: bool                # replay cached AI answers instead of calling the API
    require_approval: bool       # ask a human before high-risk experiments
    skip_heal: bool              # stop after the report, no fixes

    # ---- CARTOGRAPHER agent (Tejas) ----
    threat_model: dict           # {single_points_of_failure[], risks[{service, weakness, evidence}], hypotheses_to_test[], source}

    # ---- EXPERIMENTER agent (Artham) ----
    proposal: Optional[dict]     # next experiment, plan.json format: {id, name, steps[{type,target,delay_s}], reason,
                                 #   hypothesis, predicted_probes[], prediction{probes_affected[], data_loss, recovers}}
    done_reason: str             # why the strategist stopped proposing

    # ---- SAFETY GOVERNOR + human gate (Artham, deterministic code) ----
    review: Optional[dict]       # {approved, reasons[], needs_human, human, by}
    rejections: int              # how many proposals were rejected in a row
    rejected_sigs: list          # ["kill:redis+kill:db", ...] never propose these again

    # ---- EXECUTOR + EVALUATOR (deterministic code, Artham) ----
    results: list                # results.json entries (see CONTRACT.md), one per experiment run
    fmea: list                   # FMEA rows from core/fmea.py, worst first

    # ---- DIAGNOSTICIAN agent (Dipen) ----
    investigations: dict         # {experiment_id: {root_cause, evidence[], affected_services[], confidence, suggested_fix, by}}

    # ---- REMEDIATOR agent (Pratham); VERIFY step is in agentic/nodes/execute.py (Artham) ----
    fixes: list                  # applied catalog fixes [{id, file, why, rows[]}]
    recommendations: list        # manual suggestions, never auto-applied [{problem, recommendation}]
    fix_attempts: int
    pending_fix: bool            # True = new fixes were just applied and must be verified
    verification: Optional[dict] # {compare[{id, failure_mode, rpn_before, rpn_after, reduction_pct}], improved, results[]}

    # ---- REPORTER agent (Tejas) ----
    report: Optional[dict]       # {path_md, resilience_score, grade, summary}
