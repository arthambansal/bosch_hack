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
    out = ['<h2>Service Ã— fault heatmap</h2><p>Cells describe whole-experiment observations, not isolated causal effects. Grey means untested or unknown; red adverse; amber aborted; green probe recovery with zero recorded loss.</p><table border="1"><tr><th>Service</th>']
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
        f.write('<h2>Fault tree</h2><div style="text-align:center;border:2px solid #475569;padding:18px">Accepted vote not counted</div><p style="text-align:center">â†“ OR â†“</p><div style="display:flex;gap:12px">')
        for branch in ("Queue contents lost â€” hypothesis", "Consumer unavailable â€” check stuck-service evidence", "DB write fails after pop â€” hypothesis"):
            f.write('<div style="flex:1;border:1px solid #94a3b8;padding:18px">' + html.escape(branch) + '</div>')
        f.write('</div><p>This is a qualitative OR tree. Recorded aggregate loss does not establish any individual branch or probability.</p>')
        f.write(heatmap_html(results, services))


# Day 2 interfaces: preserve missing measurements as null.
from pathlib import Path
from .common import LIVE, RUNS_DIR


def _warning(operation, exc):
    try:
        LIVE.event("warn", f"[Reporter] {operation} not available: {exc}")
    except Exception:
        pass


def impact_of(result):
    """Aggregate fault-window request counts; never call a guard breach an outage interval."""
    missing = {"experiment": None, "votes_lost": None, "votes_accepted": None,
               "outage_s": None, "failed_requests_pct": None, "summary": "Impact not available"}
    try:
        d = result.get("delivery") or {}
        probes = result.get("probes") or {}
        measured = [p for p in probes.values() if _seconds(p.get("n")) and _seconds(p.get("ok"))
                    and p["ok"] <= p["n"]]
        n = sum(p["n"] for p in measured)
        # Partial counters would bias the aggregate; leave it unknown instead.
        pct = round(100 * sum(p["n"] - p["ok"] for p in measured) / n, 2) if n and len(measured) == len(probes) else None
        outage = None
        label = "outage not available"
        # Current engine retains only summaries, so intervals cannot be reconstructed.
        # A producer may supply an explicit measured outage; never derive it from rolling error rates.
        durations = [p.get("outage_s") for p in probes.values()]
        if len(durations) == 1 and _seconds(durations[0]):
            outage = durations[0]
            label = f"entry probe failed for {outage:g} s"
        elif probes and len(measured) == len(probes) and n and all(p["n"] > 0 and p["ok"] == p["n"] for p in measured):
            outage = 0
            label = "no failed requests observed in the fault window"
        elif _seconds(result.get("fault_window_s")) and result.get("status") in ("completed", "aborted"):
            outage = result["fault_window_s"]
            label = f"fault window {outage:g} s used as outage proxy (outage duration not measured)"
        lost = d.get("lost") if _seconds(d.get("lost")) else None
        accepted = d.get("sent") if _seconds(d.get("sent")) else None
        loss_text = f"{lost:g} of {accepted:g} accepted votes recorded lost" if lost is not None and accepted is not None else "vote loss or accepted count not available"
        return {"experiment": result.get("id"), "votes_lost": lost, "votes_accepted": accepted,
                "outage_s": outage, "failed_requests_pct": pct, "summary": loss_text + "; " + label + "."}
    except Exception as exc:
        _warning("impact", exc)
        return missing


def scorecard(results, verification, trials):
    """Count explicit verdicts; unknown/missing datasets are never perfect scores."""
    missing = {"predictions": {"right": None, "total": None},
               "mystery": {"trials": None, "top1": None, "top3": None, "target": None},
               "fixes": {"verified": None, "rolled_back": None, "not_improved": None}, "memory_hits": None}
    try:
        checks = [r["prediction_check"] for r in (results or []) if r.get("prediction_check")]
        if any(not isinstance(c, dict) for c in checks):
            raise ValueError("invalid prediction checks")
        predictions = {"right": sum(all(v is not False for v in c.values()) for c in checks), "total": len(checks)}
        mystery = {"trials": len(trials) if trials is not None else None}
        for key in ("top1", "top3", "target"):
            flags = [(t.get("correct") or {}).get(key) for t in (trials or [])]
            mystery[key] = sum(v is True for v in flags) if trials is not None and all(type(v) is bool for v in flags) else None
        statuses = (verification or {}).get("fix_status")
        fixes = {k: sum(v == k for v in statuses.values()) if isinstance(statuses, dict) else None
                 for k in ("verified", "rolled_back", "not_improved")}
        flags = [r.get("memory_hit") for r in (results or [])]
        flags += [(t.get("guess") or {}).get("memory_hit") for t in (trials or [])]
        known = [x for x in flags if type(x) is bool]
        return {"predictions": predictions, "mystery": mystery, "fixes": fixes,
                "memory_hits": sum(known) if known else None}
    except Exception as exc:
        _warning("scorecard", exc)
        return missing


def postmortem(result, investigation, impact):
    """Evidence excerpts remain attributed; absent timeline and fixes stay unavailable."""
    try:
        L = [f"### {result.get('id', '?')}: {result.get('name', 'Experiment')}",
             "", "#### Summary", impact.get("summary", "Not available"), "", "#### Impact"]
        for key in ("votes_lost", "votes_accepted", "outage_s", "failed_requests_pct"):
            value = impact.get(key)
            L.append(f"- {key}: {value if value is not None else 'Not available'}")
        L += ["", "#### Timeline", "Guard times are seconds since injection; event timestamps keep their original units."]
        events = (result.get("observation") or {}).get("events") or result.get("events") or []
        for event in events:
            stamp = event.get("t", event.get("time", event.get("timestamp")))
            L.append(f"- {stamp if stamp is not None else 'Time not available'}: " + json.dumps(event, ensure_ascii=False))
        for event in result.get("guard_log") or []:
            L.append(f"- +{event.get('t', 'unknown')} s: {'; '.join(event.get('reasons') or [])}")
        if not events and not result.get("guard_log"):
            L.append("- Timestamped events not available.")
        L += ["", "#### Root cause", investigation.get("root_cause") or "Not available; diagnosis required."]
        evidence = investigation.get("evidence") or []
        L += ["> " + str(e).replace("\n", "\n> ") for e in evidence]
        if not evidence:
            L.append("Evidence quotes not available.")
        reason = result.get("abort_reason") or ""
        L += ["", "#### What went well", f"- Guard/STOP: {reason}" if "kill switch" in reason.lower()
              else "- Kill-switch activation not recorded.", "", "#### Action items",
              "- " + str(investigation.get("suggested_fix") or "Fix recommendation not available.")]
        L.append("- Code suggestion: " + str(investigation.get("code_suggestion") or "Not available; no code patch applied by Reporter."))
        return "\n".join(L)
    except Exception as exc:
        _warning("postmortem", exc)
        return "### Postmortem\nNot available."


def day2_sections(state):
    """Report-owned integration: no additions to the shared graph-state contract."""
    try:
        from .regression import list_scenarios
        trial_path = Path(RUNS_DIR) / "mystery_trials.jsonl"
        trials = None
        if trial_path.exists():
            try:
                trials = [json.loads(line) for line in trial_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            except Exception as exc:
                _warning("mystery trial history", exc)
        results = state.get("results") or []
        investigations = state.get("investigations") or {}
        enriched = [dict(r, memory_hit=investigations.get(r.get("id"), {}).get("memory_hit", r.get("memory_hit"))) for r in results]
        card = scorecard(enriched, state.get("verification"), trials)
        L = ["## AI scorecard", "", "Prediction and fix counts cover this run; mystery counts cover the saved trial history. Memory hits count explicit hit flags in those records.", ""]
        for group, values in card.items():
            if isinstance(values, dict):
                L.append(f"- {group}: " + ", ".join(f"{k}={v if v is not None else 'Not available'}" for k, v in values.items()))
            else:
                L.append(f"- {group}: {values if values is not None else 'Not available'}")
        L += ["", "## Impact", ""]
        L += [f"- {r.get('id')}: {impact_of(r)['summary']} Failed requests: {impact_of(r)['failed_requests_pct']}% (null means not available)." for r in results]
        L += ["", "## Postmortems", ""]
        for result in results:
            investigation = dict(investigations.get(result.get("id"), {}))
            relevant = [f for f in state.get("fixes") or [] if result.get("id") in f.get("rows", f.get("for", []))]
            if relevant:
                investigation["suggested_fix"] = "; ".join(
                    f"{f['id']}: {f.get('why', 'reason not available')} (status {(state.get('verification') or {}).get('fix_status', {}).get(f['id'], f.get('status', 'Not available'))})"
                    for f in relevant)
                patches = [f.get("diff") for f in relevant if f.get("kind") == "code_suggestion" and f.get("diff")]
                if patches:
                    investigation["code_suggestion"] = "\n".join(patches)
            L.append(postmortem(result, investigation, impact_of(result)))
        L += ["", "## Never-again scenarios", ""]
        scenarios = list_scenarios()
        L += [f"- {r['file']}: {r['invariant']}; {r['last_status']}; last run {r['last_run_at']}" for r in scenarios]
        if not scenarios:
            L.append("No exported scenarios available. A confirmed failure with investigation evidence is required.")
        L += ["", "## Before / after", "", "RPN values describe verification trials; rolled-back results do not describe the retained configuration.", "", "| Fix | Experiment | RPN before | RPN after | Status |", "|---|---|---|---|---|"]
        ver = state.get("verification") or {}
        fixes = {f['id']: f for f in state.get("fixes") or []}
        statuses = ver.get("fix_status") or {}
        comparisons = {c['id']: c for c in ver.get("compare") or []}
        for fid in sorted(set(fixes) | set(statuses) | set(state.get("rolled_back") or [])):
            fix = fixes.get(fid, {})
            status = statuses.get(fid, "rolled_back" if fid in (state.get("rolled_back") or []) else fix.get("status", "Not available"))
            ids = fix.get("rows", fix.get("for", []))
            # The verifier drops rolled-back fix metadata; never guess which rows it owned.
            for rid in ids or [None]:
                c = comparisons.get(rid, {})
                own = next((x for x in fix.get("rpn", []) if x.get("id") == rid), {})
                if own:
                    c = {"rpn_before": own.get("before"), "rpn_after": own.get("after")}
                L.append(f"| {fid} | {rid or 'Not available'} | {c.get('rpn_before', 'Not available')} | {c.get('rpn_after', 'Not available')} | {status} |")
        if not fixes and not statuses:
            L.append("Fix verification not available.")
        return L
    except Exception as exc:
        _warning("Day 2 sections", exc)
        return ["## Day 2 report", "Not available."]
