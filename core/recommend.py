"""One ranked "Recommended fixes" table for the end of a run (terminal + report.md).

Pure function over the run state: no Docker, no AI. Every row says WHAT to change, WHICH experiments it answers,
the risk it carries (sum of the FMEA RPNs it addresses, before -> after when it was re-tested) and its status.
Ranking = most risk addressed first, so the first row is the fix that matters most."""
from .heal import select_fixes

STATUS_TEXT = {"verified": "VERIFIED (risk dropped)", "not_improved": "APPLIED, NOT IMPROVED", "rolled_back": "ROLLED BACK (made it worse)",
               "applied": "APPLIED (not re-tested)", "proposed": "SUGGESTED (code, not applied)"}


def _row(fid, how, rows, fmea, status, rpn_pairs=None, why=""):
    before = sum(fmea[r]["rpn"] for r in rows if r in fmea)
    after = None
    if rpn_pairs:
        before = sum(p["before"] for p in rpn_pairs)
        after = sum(p["after"] for p in rpn_pairs)
    return {"fix": fid, "how": how, "for": list(rows), "rpn_before": before, "rpn_after": after, "status": status, "why": why}


def build(state, live_entries=None):
    fmea = {r["id"]: r for r in state.get("fmea") or []}
    out, seen = [], set()
    for e in live_entries or []:
        status = e.get("status", "applied")
        text = "ROLLBACK FAILED (still applied, made it worse)" if e.get("rollback_failed") else STATUS_TEXT.get(status, status)
        how = "code change (suggestion only)" if status == "proposed" else "compose fix (applied in the sandbox)"
        out.append(_row(e.get("id", "?"), how, e.get("for") or [], fmea, text, e.get("rpn") or None, e.get("why", "")))
        seen.add(e.get("id"))
    try:
        candidates = select_fixes(list(fmea.values()), state.get("results") or [], state.get("graph") or {})
    except Exception:  # noqa: BLE001 - the table is a summary, never a reason to fail a run
        candidates = []
    for f in candidates:
        if f["id"] not in seen:
            reason = "healing was off (--no-heal)" if state.get("skip_heal") else "docker compose did not apply it"
            out.append(_row(f["id"], "compose fix", f.get("rows", []), fmea, f"RECOMMENDED, NOT APPLIED ({reason})", None, f.get("why", "")))
    for r in state.get("recommendations") or []:
        out.append(_row((r.get("problem") or "manual change")[:60], "manual / architecture change", [], fmea, "MANUAL (not auto-applied)", None, r.get("recommendation", "")))
    out.sort(key=lambda r: -(r["rpn_before"] or 0))
    return out


def render(rows):
    if not rows:
        return "No fixes recommended: no finding needed one."
    head = f"{'#':>2}  {'fix':<22} {'answers':<12} {'risk before->after':<19} status"
    lines = ["RECOMMENDED FIXES (most risk first)", head, "-" * len(head)]
    for i, r in enumerate(rows, 1):
        risk = f"{r['rpn_before']} -> {r['rpn_after']}" if r["rpn_after"] is not None else (str(r["rpn_before"]) if r["rpn_before"] else "-")
        lines.append(f"{i:>2}  {r['fix'][:22]:<22} {','.join(r['for'])[:12] or '-':<12} {risk:<19} {r['status']}")
        if r["why"]:
            lines.append(f"      why: {r['why'][:150]}")
    return "\n".join(lines)


def markdown(rows):
    if not rows:
        return ["## Recommended fixes", "", "No fixes recommended: no finding needed one."]
    out = ["## Recommended fixes (ranked by risk addressed)", "", "| # | Fix | Type | Answers | Risk before -> after | Status |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        risk = f"{r['rpn_before']} -> {r['rpn_after']}" if r["rpn_after"] is not None else (str(r["rpn_before"]) if r["rpn_before"] else "-")
        out.append(f"| {i} | {r['fix']} | {r['how']} | {', '.join(r['for']) or '-'} | {risk} | {r['status']} |")
    return out + [""] + [f"- **{r['fix']}**: {r['why']}" for r in rows if r["why"]]
