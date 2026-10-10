import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.heal import select_fixes


GRAPH = {
    "services": {
        "db": {"role": "database"},
        "worker": {"role": "worker"},
        "result": {"role": "frontend"},
        "redis": {"role": "queue"},
    }
}


def row(exp_id):
    return {"id": exp_id, "action_priority": "High"}


def run(exp_id, steps, stuck=None, lost=0):
    result = {
        "id": exp_id,
        "steps": steps,
        "stuck_services": stuck or [],
        "delivery": {"lost": lost},
    }
    return select_fixes([row(exp_id)], [result], GRAPH)


# A database kill with dependent services stuck should select recovery.
cascade = run(
    "E3",
    [{"type": "kill", "target": "db"}],
    stuck=["result", "worker"],
)
cascade_ids = {fix["id"] for fix in cascade}
assert "postgres-recovery" in cascade_ids, cascade_ids
assert "restart-policy" in cascade_ids, cascade_ids

# A database kill without stuck services must not assume recovery failed.
recovered = run(
    "E4",
    [{"type": "kill", "target": "db"}],
)
recovered_ids = {fix["id"] for fix in recovered}
assert "postgres-recovery" not in recovered_ids, recovered_ids

# A stuck worker after a Redis fault must not trigger PostgreSQL recovery.
redis_stuck = run(
    "E7",
    [{"type": "kill", "target": "redis"}],
    stuck=["worker"],
)
redis_stuck_ids = {fix["id"] for fix in redis_stuck}
assert "postgres-recovery" not in redis_stuck_ids, redis_stuck_ids
assert "restart-policy" in redis_stuck_ids, redis_stuck_ids

# Queue-related data loss should retain Redis durability remediation.
redis_loss = run(
    "E5",
    [{"type": "kill", "target": "redis"}],
    lost=2,
)
redis_ids = {fix["id"] for fix in redis_loss}
assert "redis-durable" in redis_ids, redis_ids

print("ALL HEAL SELECTION CHECKS PASSED")
