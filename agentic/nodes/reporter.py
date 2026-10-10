"""REPORTER (deterministic numbers + AI narrative). Owner: Tejas. See blueprint 14.

Job: the findings report the judges read (deliverable 4). Writes runs/<run>/report.md.
Now: deterministic report (FMEA ranking, resilience score, root causes, fixes, before/after, recommendations).
Upgrade (Tejas): add an AI-written executive summary + "what we learned" via core/llm.ask_json(kind="report_summary"),
told to use ONLY numbers present in the state; keep this deterministic version as the fallback.
"""
import os

from core.common import LIVE
from core.recommend import build as build_fix_table, render as render_fix_table, markdown as fix_table_markdown
from core.regression import export_scenario, list_scenarios
from core.report_extras import executive_summary, timing_markdown, fault_tree_markdown, write_html, day2_sections

from ..runtime import run_dir


def resilience_score(rows):
    """100 = nothing hurt. Each finding costs RPN/10 points, weighted toward the worst ones. Deterministic."""
    if not rows:
        return 100, "A"
    worst = sorted((r["rpn"] for r in rows), reverse=True)
    penalty = sum(rpn / 10 * w for rpn, w in zip(worst, [0.5, 0.25, 0.15, 0.1] + [0.0] * len(worst)))
    score = max(0, round(100 - penalty))
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"
    return score, grade


def reporter_node(state):
    LIVE.set(agent_active="reporter")
    rows, inv = state.get("fmea", []), state.get("investigations", {})
    score, grade = resilience_score(rows)
    ver = state.get("verification") or {}
    after_score = None
    if ver.get("compare"):
        by = {c["id"]: c["rpn_after"] for c in ver["compare"]}
        after_score = resilience_score([{**r, "rpn": by.get(r["id"], r["rpn"])} for r in rows])
    L = [f"# ChaosPilot findings report", "",
         f"**Resilience score: {score}/100 (grade {grade})**" + (f" -> verification trials: {after_score[0]}/100 ({after_score[1]})" if after_score else ""),
         "", f"Experiments run: {len(state.get('results', []))}. Stop reason: {state.get('done_reason', 'n/a')}.", ""]
    tm = state.get("threat_model") or {}
    try:
        summary = executive_summary(state, score, grade)
    except Exception as exc:
        LIVE.event("warn", f"[Reporter] AI summary unavailable: {type(exc).__name__}")
        summary = f"{len(state.get('results', []))} experiment records; resilience score {score}/100 (grade {grade})."
    L += ["## Executive summary", "", summary, ""]
    if tm:
        L += ["## Recon (before any attack)", f"Single points of failure: {', '.join(tm.get('single_points_of_failure') or []) or 'none found'}", ""]
        L += [f"- Hypothesis: {h}" for h in tm.get("hypotheses_to_test", [])] + [""]
    L += ["## Weaknesses ranked by risk (FMEA)", "", "| Rank | ID | Failure mode | Effect | S | O | D | RPN | Priority |",
          "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {i} | {r['id']} | {r['failure_mode']} | {r['effect']} | {r['S']} | {r['O']} | {r['D']} | {r['rpn']} | {r['action_priority']} |"
          for i, r in enumerate(rows, 1)]
    if inv:
        L += ["", "## Root causes (InvestigatorAgent)"]
        for k, v in inv.items():
            L += [f"### {k}: {v.get('root_cause')}", f"Confidence: {v.get('confidence')} (by {v.get('by')})"]
            L += [f"- evidence: {e}" for e in v.get("evidence", [])] + [f"- suggested fix: {v.get('suggested_fix')}", ""]
    for result in state.get("results", []):
        export_scenario(result, inv.get(result.get("id"), {}), run_dir())
    LIVE.set(regression=list_scenarios())
    report_state = dict(state)
    # Verifier removes rolled-back entries from graph state; its current-run live entries retain their RPNs.
    if LIVE.state.get("run_dir") == run_dir():
        entries = LIVE.state.get("fixes") or []
        if entries:
            report_state["fixes"] = entries
    L += [""] + day2_sections(report_state)
    if state.get("fixes"):
        L += ["## Fixes applied in the sandbox (RemediatorAgent)"] + [f"- **{f['id']}** for {', '.join(f.get('rows', f.get('for', [])))}: {f['why']}" for f in state["fixes"]]
    if ver.get("compare"):
        L += ["", "## Before vs after (Verifier)", "", "| ID | Failure mode | RPN before | RPN after | Reduction |", "|---|---|---|---|---|"]
        L += [f"| {c['id']} | {c['failure_mode']} | {c['rpn_before']} | {c['rpn_after']} | {c['reduction_pct']}% |" for c in ver["compare"]]
    fix_rows = build_fix_table(state, report_state.get("fixes") if LIVE.state.get("run_dir") == run_dir() else None)
    L += [""] + fix_table_markdown(fix_rows)
    if state.get("recommendations"):
        L += ["", "## Further recommendations (manual, not auto-applied)"] + [f"- {r.get('problem')}: {r.get('recommendation')}" for r in state["recommendations"]]
    L += [""] + timing_markdown(state.get("results", []))
    L += [""] + fault_tree_markdown(state.get("results", []))
    L += ["", "## Heatmap", "", "The service Ã— fault heatmap is in report.html. Combined experiments are labelled; untested cells remain unknown."]
    path = os.path.join(run_dir(), "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    write_html(os.path.join(run_dir(), "report.html"), "\n".join(L), state.get("results", []), (state.get("graph") or {}).get("services", {}))
    LIVE.event("ok", f"[Reporter] report written: {path} (resilience {score}/100, grade {grade})")
    LIVE.set(score={"overall": score, "grade": grade, "after": after_score})
    return {"report": {"path_md": path, "resilience_score": score, "grade": grade,
                       "after": after_score[0] if after_score else None, "summary": summary,
                       "fix_table": render_fix_table(fix_rows)}}
