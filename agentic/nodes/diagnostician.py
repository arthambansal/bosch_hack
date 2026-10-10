"""DIAGNOSTICIAN AGENT (evidence-based root-cause analysis). Owner: Dipen. See blueprint 6.3 and 11.

Runs only after a suspicious result (crash cascade, lost votes, no recovery, kill switch, wrong prediction).
Day 1: topology and measured evidence, read-only log/state tools, baseline
comparison, validated citations and a deterministic fallback. Existing state
fields are preserved; fix suggestions are empty until a later phase.
"""
from core.agentkit import ReActAgent
from core.common import LIVE
from core.tools import make_tools
from core.analysis_tools import evidence_context

from ..runtime import cfg

INVESTIGATION_SCHEMA = {"root_cause": "one or two sentences", "evidence": ["quote or number from a tool"],
                        "affected_services": ["service"], "confidence": "high|medium|low",
                        "suggested_fix": "empty string; fix recommendations are deferred"}


def investigate(cfg, graph, res, offline=False, baseline=None):
    facts = evidence_context(res, graph, baseline)
    agent = ReActAgent(
        "Diagnostician",
        "an SRE doing root-cause analysis right after a chaos experiment. Use read-only tools (logs, container "
        "state, queue depth, database count, config) to explain WHY the system behaved the way it did. "
        "Separate injection metadata from observed effects. Topology narrows suspects but does not prove "
        "dependency health. Do not claim missing restart policies, permanent data loss, persistence "
        "settings, or event timing without evidence. Current tool readings are post-experiment snapshots. "
        "Quote exact evidence strings from context or tools. Use medium confidence only when topology "
        "and mechanism evidence agree; otherwise low. High confidence requires confirmed intervention "
        "and is unavailable on Day 1. Return suggested_fix as an empty string.",
        make_tools(cfg, graph), INVESTIGATION_SCHEMA, max_steps=5, offline=offline)
    final, trace = agent.run(f"Explain the root cause of what happened in experiment {res.get('id')}.", facts)
    return {"final": final, "tool_calls": len(trace), "trace": trace}


def rule_based(res, graph=None):
    stuck, details = res.get("stuck_services") or [], res.get("stuck_details") or {}
    lost = (res.get("delivery") or {}).get("lost") or 0
    if stuck:
        context = evidence_context(res, graph or {})
        suspects = context["topology"]["candidates"]
        dns = [s for s in suspects if any("name or service not known" in str(line).lower()
               or "enotfound" in str(line).lower() for line in details.get(s, {}).get("last_logs", []))]
        cause = (f"{', '.join(dns)} remained stopped; its logs contain a DNS resolution failure. "
                 "DNS failure is a supported mechanism candidate; onset timing is unconfirmed." if dns else
                 f"{', '.join(suspects)} remained stopped and is a topology-based cause candidate; "
                 "the exit mechanism is not established.")
        return {"root_cause": cause, "evidence": context["measured_evidence"],
                "affected_services": stuck,
                "confidence": "medium" if dns and graph else "low", "suggested_fix": ""}
    if lost:
        return {"root_cause": f"{lost} accepted votes were undelivered at the measurement cutoff; "
                              "the cause and permanent loss are not established",
                "evidence": [f"delivery audit: {res['delivery']}"], "affected_services": [],
                "confidence": "low", "suggested_fix": ""}
    return {"root_cause": res.get("abort_reason") or "behaviour differed from the prediction",
            "evidence": evidence_context(res, graph or {})["measured_evidence"],
            "affected_services": [], "confidence": "low", "suggested_fix": ""}


def validated_final(final, context, trace, graph):
    """Reject malformed or unsupported citations instead of trusting model JSON."""
    if not isinstance(final, dict):
        return None
    if not isinstance(final.get("root_cause"), str) or not final["root_cause"].strip():
        return None
    citations = final.get("evidence")
    services = final.get("affected_services")
    if not isinstance(citations, list) or not citations or not all(isinstance(e, str) and e.strip() for e in citations):
        return None
    if not isinstance(services, list) or not all(isinstance(s, str) and s in graph.get("services", {}) for s in services):
        return None
    sources = context["measured_evidence"] + [str(t.get("observation", "")) for t in trace
                                            if t.get("tool") and not str(t.get("observation", "")).startswith(("tool error", "bad arguments", "unknown tool"))]
    if not all(any(citation in source for source in sources) for citation in citations):
        return None
    if final.get("confidence") not in ("low", "medium", "high"):
        return None
    # No intervention or signature evidence is collected in this Day-1 node.
    return {"root_cause": final["root_cause"], "evidence": citations,
            "affected_services": services, "confidence": "low", "suggested_fix": ""}


def diagnostician_node(state):
    LIVE.set(agent_active="diagnostician")
    if not state.get("results"):
        return {"investigations": dict(state.get("investigations") or {})}
    res = state["results"][-1]
    graph = state.get("graph") or {}
    context = evidence_context(res, graph, state.get("baseline"))
    try:
        out = investigate(cfg(), graph, res, offline=state.get("offline", False),
                          baseline=state.get("baseline"))
        final = validated_final(out.get("final"), context, out.get("trace") or [], graph)
    except Exception as exc:
        LIVE.event("warn", f"[Diagnostician] evidence reasoning unavailable ({type(exc).__name__}); using rules")
        final = None
    by = "agent" if final else "rules"
    final = final or rule_based(res, graph)
    final["by"] = by
    LIVE.event("ai", f"[Diagnostician] {res['id']} root cause: {final.get('root_cause')}")
    inv = dict(state.get("investigations") or {})
    inv[res["id"]] = final
    return {"investigations": inv}
