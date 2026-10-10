"""root_cause and report alerts are sent after the Diagnostician and the Reporter, with the notify(kind, title, text, fields) signature.
No Docker, no network. Run: PYTHONPATH=. python3 tests/test_notify_hooks.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import inspect  # noqa: E402

import core.notify as N  # noqa: E402
from agentic.graph import announced  # noqa: E402

calls, checks = [], {}
N.notify = lambda kind, title, text, fields=None: calls.append((kind, title, text, fields)) or True

diag = announced("diagnostician", lambda s: {"investigations": {"E1": {"root_cause": "worker lost redis", "confidence": 0.8, "by": "ai"},
                                                               "E0": {"root_cause": "old"}}})
diag({"investigations": {"E0": {"root_cause": "old"}}})
checks["root_cause alert sent once, only for the new investigation"] = [c[0] for c in calls] == ["root_cause"] and "E1" in calls[0][1]
rep = announced("reporter", lambda s: {"report": {"resilience_score": 61, "grade": "D", "after": 80, "path_md": "runs/x/report.md"}})
rep({})
checks["report alert sent with score and grade"] = calls[-1][0] == "report" and "61/100" in calls[-1][2] and "80/100" in calls[-1][2]
checks["other nodes are untouched"] = announced("executor", len) is len
N.notify = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("discord down"))
checks["a failing notifier never changes the node result"] = announced("reporter", lambda s: {"report": {"grade": "A"}})({}) == {"report": {"grade": "A"}}
import ast  # noqa: E402
import glob  # noqa: E402

KINDS = {"kill_switch", "root_cause", "fix_verified", "fix_rolled_back", "mystery_reveal", "report", "gray_failure"}
bad, found = [], 0
for path in glob.glob("core/*.py") + glob.glob("agentic/**/*.py", recursive=True):
    for node in ast.walk(ast.parse(open(path).read())):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) in ("notify", "_notify"):
            found += 1
            kind = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
            if len(node.args) not in (3, 4) or (kind is not None and kind not in KINDS):
                bad.append(f"{path}:{node.lineno}")
checks["every notify call site matches notify(kind, title, text, fields=None) with a valid kind"] = found >= 6 and not bad
if bad:
    print("bad call sites:", bad)
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
print("ALL CHECKS PASSED" if all(checks.values()) else "SOME CHECKS FAILED")
sys.exit(0 if all(checks.values()) else 1)
