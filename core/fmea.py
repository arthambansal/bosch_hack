"""Automated FMEA (Failure Mode and Effects Analysis) built from REAL chaos-experiment measurements.

FMEA is the standard automotive quality method (Bosch engineers use it daily). Each failure mode gets
  S = Severity   (1-10)  how bad is the measured effect?
  O = Occurrence (1-10)  how likely is this failure in real life?   (documented prior per fault type)
  D = Detection  (1-10)  how hard is it to notice?  10 = nobody would notice
  RPN = S x O x D        (1-1000)  ranks what to fix first
Action Priority (simplified AIAG-VDA): High if S>=9 or RPN>=200, Medium if S>=7 or RPN>=100, else Low.

S and D come from MEASUREMENTS, not from an LLM guess. Only O is a prior (assumption, stated openly).
After a fix is applied we re-run and RE-SCORE: that is the FMEA "corrective action -> re-evaluate" loop.
"""

# Occurrence prior: how common each fault is in production (assumption; edit with team consensus).
O_PRIOR = {"kill": 7, "pause": 3, "partition": 5, "latency": 6, "spike": 6}


def _max(result, key):
    vals = [(p.get(key) or 0) for p in (result.get("probes") or {}).values()]
    return max(vals) if vals else 0


def _slowdown(result, baseline):
    """Worst p95 latency ratio vs baseline (baseline floor 50 ms to ignore noise)."""
    worst = 0.0
    for name, p in (result.get("probes") or {}).items():
        base = ((baseline or {}).get("probes", {}).get(name, {}) or {}).get("p95_ms") or 0
        worst = max(worst, (p.get("p95_ms") or 0) / max(base, 50))
    return worst


def _lost(result):
    return (result.get("delivery") or {}).get("lost") or 0


def severity(r, baseline):
    err, lost = _max(r, "error_rate"), _lost(r)
    if lost > 0:
        s, effect = 10, f"{lost} accepted votes silently lost (data integrity violated)"
    elif r.get("recovery_s") is None or r.get("stuck_services"):
        stuck = r.get("stuck_services")
        s, effect = 9, (f"cascade: {', '.join(stuck)} crashed and never restarted on their own" if stuck
                        else "system did not recover on its own after the fault ended")
    elif err >= 0.9:
        s, effect = 8, f"near-total outage ({err:.0%} of requests failed)"
    elif err >= 0.5:
        s, effect = 7, f"major outage ({err:.0%} of requests failed)"
    elif err >= 0.2:
        s, effect = 5, f"partial outage ({err:.0%} of requests failed)"
    elif err > 0.05:
        s, effect = 3, f"minor errors ({err:.0%} of requests failed)"
    else:
        ratio = _slowdown(r, baseline)
        s, effect = (4, f"latency up {ratio:.1f}x vs baseline") if ratio >= 3 else \
                    (3, f"latency up {ratio:.1f}x vs baseline") if ratio >= 1.5 else (1, "no user-visible effect")
    surprise = [n for n, p in (r.get("probes") or {}).items()
                if n not in (r.get("predicted_probes") or []) and (p.get("error_rate") or 0) >= 0.5]
    if surprise:
        s, effect = min(10, s + 1), effect + f"; UNPREDICTED spread to {', '.join(surprise)}"
    return s, effect


def occurrence(r):
    prior = [O_PRIOR.get(st["type"], 5) for st in r.get("steps", [])] or [5]
    return max(2, min(prior) - (1 if len(prior) > 1 else 0))   # combined failures are rarer


def detection(r, baseline):
    if _lost(r) > 0:
        return 10, "no live monitor sees lost data (only found by our post-run delivery audit)"
    if r.get("stuck_services"):
        return 10, "health pages look normal again; the crashed service is only visible by inspecting containers"
    times = [p["time_to_first_error_s"] for p in (r.get("probes") or {}).values()
             if p.get("time_to_first_error_s") is not None]
    if times:
        t = min(times)
        d = 2 if t <= 1 else 3 if t <= 3 else 5 if t <= 5 else 7 if t <= 10 else 9
        return d, f"first user-facing error after {t}s"
    if _slowdown(r, baseline) >= 1.5:
        return 6, "only visible as slower responses, no errors"
    return 10, "no observable symptom"


def action_priority(s, rpn):
    return "High" if (s >= 9 or rpn >= 200) else "Medium" if (s >= 7 or rpn >= 100) else "Low"


def build_fmea(results, baseline):
    rows = []
    for r in results:
        if r.get("status") == "refused":
            continue
        s, effect = severity(r, baseline)
        o = occurrence(r)
        d, d_note = detection(r, baseline)
        rpn = s * o * d
        rows.append({
            "id": r["id"],
            "failure_mode": " then ".join(f"{st['type']} {st['target']}" for st in r.get("steps", [])),
            "effect": effect, "S": s, "O": o, "D": d, "rpn": rpn,
            "action_priority": action_priority(s, rpn), "detection_note": d_note,
            "evidence": {"error_rate": _max(r, "error_rate"), "recovery_s": r.get("recovery_s"),
                         "lost_votes": _lost(r), "killswitch": r.get("status") == "aborted"},
        })
    return sorted(rows, key=lambda x: -x["rpn"])


def compare_fmea(before, after):
    """Before/after table: the proof that a fix worked."""
    aft = {r["id"]: r for r in after}
    out = []
    for b in before:
        a = aft.get(b["id"])
        if not a:
            continue
        out.append({"id": b["id"], "failure_mode": b["failure_mode"], "rpn_before": b["rpn"],
                    "rpn_after": a["rpn"], "S": [b["S"], a["S"]], "D": [b["D"], a["D"]],
                    "reduction_pct": round(100 * (b["rpn"] - a["rpn"]) / b["rpn"]) if b["rpn"] else 0})
    return out


def format_table(rows):
    lines = [f"{'ID':4} {'FAILURE MODE':32} {'S':>2} {'O':>2} {'D':>2} {'RPN':>4}  {'ACTION':6}  EFFECT"]
    for r in rows:
        lines.append(f"{r['id']:4} {r['failure_mode'][:32]:32} {r['S']:>2} {r['O']:>2} {r['D']:>2} "
                     f"{r['rpn']:>4}  {r['action_priority']:6}  {r['effect']}")
    return "\n".join(lines)
