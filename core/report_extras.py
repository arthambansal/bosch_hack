"""Evidence-derived reporting; missing measurements remain unknown."""
import html
import json
import math
import statistics

from .llm import ask_json


def _seconds(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def timing_rows(results):
    rows = []
    for r in results:
        # Only Observer summary fields constitute end-to-end detection/recovery evidence.
        # Legacy first-error and recovery fields describe HTTP probes, not vote delivery.
        observation = r.get("observation") or {}
        rows.append({"id": r.get("id", "?"),
                     "failure_mode": "+".join(f"{s.get('type')}:{s.get('target')}" for s in r.get("steps", [])) or "unspecified",
                     "mttd_s": observation.get("mttd_s") if _seconds(observation.get("mttd_s")) else None,
                     "mttr_s": observation.get("mttr_s") if _seconds(observation.get("mttr_s")) else None,
                     "probe_first_error_s": min((p["time_to_first_error_s"] for p in r.get("probes", {}).values()
                         if _seconds(p.get("time_to_first_error_s"))), default=None),
                     "probe_recovery_s": r.get("recovery_s") if _seconds(r.get("recovery_s")) else None,
                     "status": r.get("status")})
    return rows


def timing_markdown(results):
    rows = timing_rows(results)
    fmt = lambda x: "unknown / not measured" if x is None else f"{x:g} s"
    lines = ["## Detection and recovery", "",
             "MTTD/MTTR require Observer measurements. Legacy HTTP probe timings are shown separately; they do not prove end-to-end vote recovery.", "",
             "| Experiment | MTTD | MTTR | First HTTP error | HTTP recovery after restoration |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append("| " + " | ".join([str(r["id"])] + [fmt(r[k]) for k in
                     ("mttd_s", "mttr_s", "probe_first_error_s", "probe_recovery_s")]) + " |")
    for metric in ("mttd_s", "mttr_s"):
        samples = [r[metric] for r in rows if r[metric] is not None]
        lines.append(f"Mean {metric}: {fmt(statistics.mean(samples) if samples else None)}; measured samples {len(samples)}/{len(rows)}. Unknown/non-recovery observations are not zeros.")
    lines += ["", "### Per failure mode", "", "| Fault / target | Mean MTTD | Samples | Mean MTTR | Samples |", "|---|---|---|---|---|"]
    for mode in sorted({r["failure_mode"] for r in rows}):
        group = [r for r in rows if r["failure_mode"] == mode]
        cells = [mode]
        for metric in ("mttd_s", "mttr_s"):
            samples = [r[metric] for r in group if r[metric] is not None]
            cells += [fmt(statistics.mean(samples) if samples else None), f"{len(samples)}/{len(group)}"]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def executive_summary(state, score, grade):
    """AI selects evidence statements, rather than inventing claims or numbers."""
    results = state.get("results", [])
    facts = [f"{len(results)} experiment records; resilience score {score}/100 (grade {grade})."]
    for r in results:
        facts.append(f"{r.get('id')}: status {r.get('status')}; recorded lost votes {(r.get('delivery') or {}).get('lost', 'unknown')}; stuck services {r.get('stuck_services', [])}.")
    if not results:
        facts.append("No experiment evidence was supplied; no operational resilience conclusion is available.")
    data, _ = ask_json("report_summary", "Select at most four fact IDs for an executive summary. Return only {\"fact_ids\":[0]}. Do not write claims.",
                       json.dumps(dict(enumerate(facts))), offline=state.get("offline", False))
    ids = data.get("fact_ids") if isinstance(data, dict) else None
    if not isinstance(ids, list) or not ids or len(ids) > 4 or any(type(i) is not int or not 0 <= i < len(facts) for i in ids):
        ids = list(range(min(4, len(facts))))
    return " ".join(facts[i] for i in dict.fromkeys([0] + ids))


def fault_tree_markdown(results):
    losses = [r.get("id", "?") for r in results if _seconds((r.get("delivery") or {}).get("lost")) and r["delivery"]["lost"] > 0]
    stuck = [r.get("id", "?") for r in results if "worker" in r.get("stuck_services", [])]
    return ["## Fault tree: accepted vote not counted", "",
            "```mermaid", "flowchart TD", 'T["Accepted vote not counted"] --> O{OR}',
            'O --> Q["Queue contents lost: hypothesis"]',
            'O --> W["Consumer unavailable"]', 'O --> D["DB write fails after pop: hypothesis"]', "```", "",
            f"Recorded aggregate loss: {', '.join(map(str, losses)) or 'none recorded / insufficient evidence'}. This does not localise the loss mechanism.",
            f"Worker reported stuck: {', '.join(map(str, stuck)) or 'none recorded'}. Queue loss and DB-write branches need intervention evidence; no probabilities are assigned."]


def heatmap_html(results, services):
    """Colour observed outcomes; combined experiments stay explicitly confounded."""
    cells = {}
    faults = sorted({s.get("type", "?") for r in results for s in r.get("steps", [])})
    for r in results:
        for s in r.get("steps", []):
            key = (s.get("target"), s.get("type"))
            if r.get("status") == "refused":
                label, color = "refused; not tested", "#e5e7eb"
            elif r.get("stuck_services") or ((r.get("delivery") or {}).get("lost") or 0) > 0:
                label, color = "adverse outcome", "#fecaca"
            elif r.get("status") == "aborted":
                label, color = "aborted; partial evidence", "#fde68a"
            elif r.get("recovery_s") is not None and (r.get("delivery") or {}).get("lost") == 0:
                label, color = "probe recovery; zero recorded loss", "#bbf7d0"
            else:
                label, color = "insufficient evidence", "#e5e7eb"
            if len(r.get("steps", [])) > 1:
                label += "; combined experiment"
            cells.setdefault(key, []).append((str(r.get("id")), label, color))
    esc = html.escape
    out = ['<h2>Service × fault heatmap</h2><p>Cells describe whole-experiment observations, not isolated causal effects. Grey means untested or unknown; red adverse; amber aborted; green probe recovery with zero recorded loss.</p><table border="1"><tr><th>Service</th>']
    out += [f"<th>{esc(f)}</th>" for f in faults] + ["</tr>"]
    for service in sorted(services):
        out.append(f"<tr><th>{esc(service)}</th>")
        for fault in faults:
            values = cells.get((service, fault), [])
            color = "#fecaca" if any(v[2] == "#fecaca" for v in values) else "#fde68a" if any(v[2] == "#fde68a" for v in values) else values[0][2] if values else "#e5e7eb"
            label = "; ".join(f"{i}: {v}" for i, v, _ in values) or "not tested"
            out.append(f'<td style="background:{color}">{esc(label)}</td>')
        out.append("</tr>")
    return "".join(out) + "</table>"


def write_html(path, markdown, results, services):
    with open(path, "w", encoding="utf-8") as f:
        f.write('<!doctype html><meta charset="utf-8"><title>ChaosPilot findings</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto}pre{white-space:pre-wrap}td,th{padding:10px}</style>')
        f.write("<pre>" + html.escape(markdown) + "</pre>")
        f.write('<h2>Fault tree</h2><div style="text-align:center;border:2px solid #475569;padding:18px">Accepted vote not counted</div><p style="text-align:center">↓ OR ↓</p><div style="display:flex;gap:12px">')
        for branch in ("Queue contents lost — hypothesis", "Consumer unavailable — check stuck-service evidence", "DB write fails after pop — hypothesis"):
            f.write('<div style="flex:1;border:1px solid #94a3b8;padding:18px">' + html.escape(branch) + '</div>')
        f.write('</div><p>This is a qualitative OR tree. Recorded aggregate loss does not establish any individual branch or probability.</p>')
        f.write(heatmap_html(results, services))


# ---------------------------------------------------------------- Day 2 interfaces (Tejas) — DAY2_CONTRACT.md 4.5, 5
# STUBS with safe defaults. Replace the bodies, keep the signatures.
def impact_of(result):
    """Impact of one experiment in human terms (shape 4.5)."""
    d = (result or {}).get("delivery") or {}
    return {"experiment": (result or {}).get("id"), "votes_lost": d.get("lost"), "votes_accepted": d.get("sent"),
            "outage_s": None, "failed_requests_pct": None, "summary": "Impact not computed yet"}


def scorecard(results, verification, trials):
    """AI scorecard for the report."""
    return {"predictions": {"right": None, "total": None}, "mystery": {"trials": len(trials or []), "top1": None,
            "top3": None, "target": None}, "fixes": {"verified": None, "rolled_back": None, "not_improved": None},
            "memory_hits": None}


def postmortem(result, investigation, impact):
    """Markdown postmortem section for one finding."""
    return ""
