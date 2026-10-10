"""Shape validators for the Day 2 live_state keys (docs/day2/DAY2_CONTRACT.md section 4). Owner: Artham.

Each validate_* returns a list of problems ([] = valid). Use them in your tests:
    assert validate_truth(oracle.snapshot()) == []
"""
FAULTS = {"kill", "pause", "partition", "latency", "spike"}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _opt_num(v):
    return v is None or _num(v)


def _need(d, keys, where):
    if not isinstance(d, dict):
        return [f"{where}: not an object"]
    return [f"{where}: missing '{k}'" for k in keys if k not in d]


def validate_truth(t):
    p = _need(t, ["status", "monitoring", "canaries", "invariants", "diverged_at", "updated_at"], "truth")
    if p:
        return p
    if t["status"] not in {"ok", "diverged", "down", "unknown"}:
        p.append("truth.status invalid")
    if t["monitoring"] not in {"healthy", "degraded", "unknown"}:
        p.append("truth.monitoring invalid")
    c = t["canaries"]
    p += _need(c, ["sent", "stored", "pending", "suspected_lost", "last_lag_s", "grace_s"], "truth.canaries")
    if not p and not all(_num(c[k]) for k in ("sent", "stored", "pending", "suspected_lost")):
        p.append("truth.canaries counts must be numbers")
    if not isinstance(t["invariants"], list):
        p.append("truth.invariants not a list")
    else:
        for i, inv in enumerate(t["invariants"]):
            p += _need(inv, ["name", "ok", "detail"], f"truth.invariants[{i}]")
            if isinstance(inv, dict) and inv.get("ok") not in (True, False, None):
                p.append(f"truth.invariants[{i}].ok must be true/false/null")
    if not _opt_num(t["diverged_at"]):
        p.append("truth.diverged_at must be number or null")
    if t["status"] == "diverged" and t["monitoring"] != "healthy":
        p.append("truth: diverged requires monitoring == healthy")
    return p


def validate_guess(g, services):
    p = _need(g, ["fault", "target", "confidence", "top3", "root_cause", "evidence", "memory_hit"], "guess")
    if p:
        return p
    if g["fault"] not in FAULTS:
        p.append(f"guess.fault '{g['fault']}' not in {sorted(FAULTS)}")
    if services and g["target"] not in services:
        p.append(f"guess.target '{g['target']}' not a service")
    if not (_num(g["confidence"]) and 0 <= g["confidence"] <= 1):
        p.append("guess.confidence must be 0..1")
    if not isinstance(g["top3"], list) or not 1 <= len(g["top3"]) <= 3:
        p.append("guess.top3 must have 1-3 items")
    if not isinstance(g["evidence"], list):
        p.append("guess.evidence must be a list")
    return p


def validate_mystery(m, services=None):
    p = _need(m, ["state", "trial", "menu", "chosen_by", "injected_at", "detected_at", "diagnosed_at",
                  "detected_by", "guess", "answer", "correct", "accuracy"], "mystery")
    if p:
        return p
    if m["state"] not in {"off", "idle", "injected", "detected", "diagnosed", "revealed"}:
        p.append("mystery.state invalid")
    if m["state"] != "revealed" and (m["answer"] is not None or m["correct"] is not None):
        p.append("mystery: answer/correct must be null until revealed")
    for i, item in enumerate(m["menu"] or []):
        p += _need(item, ["id", "label", "fault", "target"], f"mystery.menu[{i}]")
    if m["guess"] is not None:
        p += validate_guess(m["guess"], services)
    p += _need(m["accuracy"], ["trials", "top1", "top3", "target"], "mystery.accuracy")
    return p


def validate_memory(m):
    p = _need(m, ["last_hit", "signatures"], "memory")
    if not p and m["last_hit"] is not None:
        p += _need(m["last_hit"], ["experiment", "signature_id", "similarity", "seen_in_run", "root_cause", "saved_s"],
                   "memory.last_hit")
    return p


def validate_fixes(fixes):
    if not isinstance(fixes, list):
        return ["fixes: not a list"]
    p = []
    for i, f in enumerate(fixes):
        p += _need(f, ["id", "title", "kind", "for", "why", "diff", "status", "rpn"], f"fixes[{i}]")
        if isinstance(f, dict):
            if f.get("kind") not in {"compose", "code_suggestion"}:
                p.append(f"fixes[{i}].kind invalid")
            if f.get("status") not in {"proposed", "applied", "verified", "not_improved", "rolled_back"}:
                p.append(f"fixes[{i}].status invalid")
            if "rollback_failed" in f and not isinstance(f["rollback_failed"], bool):
                p.append(f"fixes[{i}].rollback_failed must be true/false")
            if f.get("rollback_failed") and f.get("status") != "applied":
                p.append(f"fixes[{i}]: rollback_failed means the fix is still applied")
            if f.get("rollback_failed") and not isinstance(f.get("worse"), dict):
                p.append(f"fixes[{i}]: rollback_failed needs worse={{id, before, after}}")
            if f.get("kind") == "code_suggestion" and f.get("status") != "proposed":
                p.append(f"fixes[{i}]: code suggestions are never applied")
    return p


def validate_impact(i):
    p = _need(i, ["experiment", "votes_lost", "votes_accepted", "outage_s", "failed_requests_pct", "summary"], "impact")
    if not p:
        for k in ("votes_lost", "votes_accepted", "outage_s", "failed_requests_pct"):
            if not _opt_num(i[k]):
                p.append(f"impact.{k} must be number or null")
    return p


def validate_predictions(pr):
    p = _need(pr, ["items", "right", "total"], "predictions")
    if not p:
        for j, it in enumerate(pr["items"]):
            p += _need(it, ["id", "predicted", "check", "correct"], f"predictions.items[{j}]")
    return p


def validate_regression(items):
    if not isinstance(items, list):
        return ["regression: not a list"]
    p = []
    for j, it in enumerate(items):
        p += _need(it, ["scenario_id", "file", "invariant", "last_status", "last_run_at"], f"regression[{j}]")
        if isinstance(it, dict) and it.get("last_status") not in {"pass", "fail", "never_run"}:
            p.append(f"regression[{j}].last_status invalid")
    return p


def validate_plan_ranking(pr):
    p = _need(pr, ["turn", "chosen", "reason", "types_covered", "types_required", "candidates"], "plan_ranking")
    if p:
        return p
    for j, c in enumerate(pr["candidates"]):
        p += _need(c, ["id", "type", "target", "risk_score", "predicted_probes", "tried"], f"plan_ranking.candidates[{j}]")
        if isinstance(c, dict) and c.get("type") not in FAULTS:
            p.append(f"plan_ranking.candidates[{j}].type invalid")
    scores = [c.get("risk_score") for c in pr["candidates"] if isinstance(c, dict)]
    if any(not _num(x) for x in scores) or scores != sorted(scores, reverse=True):
        p.append("plan_ranking.candidates must be sorted by risk_score, highest first")
    if len(pr["candidates"]) > 10:
        p.append("plan_ranking.candidates: at most 10")
    return p
