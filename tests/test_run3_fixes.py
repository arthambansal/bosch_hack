"""Regressions from the 3rd live run (Groq daily quota, compose rejected the AI override, backlog counted as loss).
No Docker, no network.   Run: PYTHONPATH=. python3 tests/test_run3_fixes.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests  # noqa: E402
import agentic.nodes.remediator as RM  # noqa: E402
import core.llm as L  # noqa: E402
from core.engine import account_delivery  # noqa: E402
from core.fmea import severity  # noqa: E402
from core.heal import sanitize_generated_override  # noqa: E402
from agentic.nodes.diagnostician import rule_based  # noqa: E402

checks = {}

# 1) service_healthy on a service without a healthcheck is downgraded (it broke `docker compose up` live)
ov = {"services": {"worker": {"depends_on": {"redis": {"condition": "service_healthy"}, "db": {"condition": "service_healthy"}}}}}
fixed, notes = sanitize_generated_override(json.loads(json.dumps(ov)), [])
dep = fixed["services"]["worker"]["depends_on"]
checks["override: redis/db 'healthy' without healthcheck -> service_started"] = dep["redis"]["condition"] == dep["db"]["condition"] == "service_started" and len(notes) == 2
fixed, notes = sanitize_generated_override(json.loads(json.dumps(ov)), [{"id": "postgres-healthcheck"}])
dep = fixed["services"]["worker"]["depends_on"]
checks["override: db keeps 'healthy' once postgres-healthcheck is applied; redis is downgraded"] = dep["db"]["condition"] == "service_healthy" and dep["redis"]["condition"] == "service_started"

# 2) remediator: a rejected AI override must not discard the catalog fixes, and a failed apply restores the sandbox
calls = []
RM.advise_fixes = lambda *a, **k: ([{"id": "restart-policy", "file": "restart-policy.yml", "why": "w", "rows": ["E1"]}], [], "rules")
RM.draft_ai_remediation = lambda *a, **k: ({"id": "ai-generated-override", "file": "generated/ai-override.yml", "why": "w", "rows": ["E1"]}, None)
RM.apply_fixes = lambda fixes, cfg: (calls.append([f["id"] for f in fixes]) or all(f["id"] != "ai-generated-override" for f in fixes))
RM.time.sleep = lambda s: None
state = {"fmea": [{"id": "E1"}], "results": [], "graph": {}, "fixes": [], "fix_attempts": 0}
out = RM.remediator_node(state)
checks["remediator: retries without the AI override"] = calls == [["restart-policy", "ai-generated-override"], ["restart-policy"]]
checks["remediator: keeps the catalog fix"] = out.get("pending_fix") is True and [f["id"] for f in out["fixes"]] == ["restart-policy"]
calls.clear()
RM.apply_fixes = lambda fixes, cfg: (calls.append([f["id"] for f in fixes]) or False)
out = RM.remediator_node(state)
checks["remediator: total failure restores the last good state and stops"] = out == {"pending_fix": False} and calls[-1] == []

# 3) Groq daily token quota: fail fast, remember it, no retries/sleeps
os.environ.update(OPENAI_API_KEY="k", OPENAI_BASE_URL="https://example.invalid/v1", LLM_MODEL="m-main", LLM_AGENT_MODEL="m-agent")
slept, n = [], {"calls": 0}


class Resp:
    status_code = 429
    text = '{"error":{"message":"Rate limit reached on tokens per day (TPD): Limit 200000, Used 199999"}}'
    headers = {}


def boom(*a, **k):
    n["calls"] += 1
    raise requests.HTTPError(response=Resp())


L._call = boom
L.time.sleep = lambda s: slept.append(s)
L.QUOTA_USED_UP.clear()
r1 = L.ask_json("diag", "s", "u", tool_agent=True)
r2 = L.ask_json("diag2", "s", "u2", tool_agent=True)
checks["llm: daily quota -> immediate fallback, no waiting"] = r1 == (None, "none") and not slept and n["calls"] == 1
checks["llm: exhausted model is skipped without another request"] = r2 == (None, "none") and n["calls"] == 1
L.QUOTA_USED_UP.clear()

# 4) JSON mode always contains the word 'json' (Groq rejects the request otherwise)
sent = {}


class Ok:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "{}"}}]}


import importlib  # noqa: E402
L = importlib.reload(L)
L.requests.post = lambda url, headers=None, json=None, timeout=None: (sent.update(json) or Ok())
L._call("be brief", "summarise this run", 100, json_mode=True)
checks["llm: json_object mode adds the word JSON when the prompt has none"] = "json" in sent["messages"][-1]["content"].lower()

# 5) backlog is not loss
checks["accounting: spike backlog (E5) is not lost"] = account_delivery(32358, 669, 0, 31689) == (0, 31689)
checks["accounting: E6 case lost=0"] = account_delivery(62, 520, 31689, 31231) == (0, 0)
checks["accounting: real loss still counted"] = account_delivery(22, 21, 0, 0) == (1, 0)
checks["accounting: unknown queue size keeps old behaviour"] = account_delivery(10, 4, None, None) == (6, 0)
checks["accounting: unknown delivery"] = account_delivery(10, None, 0, 0) == (None, 0)

# 6) FMEA / diagnosis understand backlog
res = {"probes": {}, "recovery_s": 0.5, "stuck_services": [], "delivery": {"sent": 100, "delivered": 5, "lost": 0, "backlog_growth": 500}}
s, effect = severity(res, {})
checks["fmea: big backlog is a medium-severity finding, not 'no effect'"] = s == 6 and "stuck in the queue" in effect
d = rule_based(res)
checks["diagnosis: backlog explained as slow worker, not loss"] = "not lost" in d["root_cause"] and "worker" in d["root_cause"]

for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
print("ALL CHECKS PASSED" if all(checks.values()) else "SOME CHECKS FAILED")
sys.exit(0 if all(checks.values()) else 1)
