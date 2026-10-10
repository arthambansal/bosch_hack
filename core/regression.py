"""NEVER AGAIN: confirmed failures become replayable scenarios. Owner: Tejas. Contract: DAY2_CONTRACT.md 4.7, 5, 6.

STUB: safe defaults. Replace the bodies, keep the signatures.
"""


def export_scenario(result, investigation, run_dir):
    """Write scenarios/<id>.json for a confirmed failure; return its path, or None if nothing was written."""
    return None


def replay(path, cfg):
    """Run one scenario through the same engine and kill switch and check its invariants. Never raises."""
    return {"scenario_id": None, "passed": False, "details": ["replay not implemented"]}


def list_scenarios():
    return []
