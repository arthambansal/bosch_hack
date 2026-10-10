import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.heal import validate_generated_override

def check(name, override, expected):
    valid, reason = validate_generated_override(override)
    assert valid == expected, f"{name}: {reason}"
    print(f"PASS {name}")

check("safe restart", {
    "services": {"worker": {"restart": "unless-stopped"}}
}, True)

check("reject arbitrary command", {
    "services": {"redis": {"command": ["sh", "-c", "echo unsafe"]}}
}, False)

check("reject healthcheck", {
    "services": {"worker": {"healthcheck": {"test": ["CMD", "true"]}}}
}, False)

check("reject privileged", {
    "services": {"worker": {"privileged": True}}
}, False)

check("reject unknown service", {
    "services": {"attacker": {"restart": "always"}}
}, False)

print("ALL REMEDIATOR SAFETY CHECKS PASSED")
