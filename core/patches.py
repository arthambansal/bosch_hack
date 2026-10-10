
"""Code-patch suggestions: LLM-assisted, review-only diffs."""

from .llm import ask_json


PATCH_SYSTEM = """You are a reliability engineer analyzing chaos-test results.

Recommend a code patch only when supported by the supplied evidence.
Never invent source files, functions, or measured values.
If the relevant source code is not supplied, return diff as null.
Never claim a patch has been applied or verified.

Return a JSON object:
{
  "title": "short title",
  "why": "evidence-based explanation",
  "diff": "unified diff text or null"
}
"""


def suggest_patches(investigations, results):
    """Return proposed code suggestions grounded in observed delivery loss."""
    if not isinstance(investigations, dict) or not isinstance(results, list):
        return []

    evidence_ids = []
    evidence = []

    for result in results:
        if not isinstance(result, dict):
            continue

        experiment_id = result.get("id")
        delivery = result.get("delivery", {})

        if not isinstance(delivery, dict):
            continue

        try:
            lost = float(delivery.get("lost", 0))
        except (TypeError, ValueError):
            continue

        if lost <= 0 or experiment_id is None:
            continue

        investigation = investigations.get(experiment_id, {})
        if not isinstance(investigation, dict):
            investigation = {}

        context = " ".join(
            str(investigation.get(key, ""))
            for key in ("root_cause", "fault", "target", "summary")
        ).lower()

        relevant = any(
            word in context
            for word in ("redis", "queue", "retry", "connection")
        )

        if not relevant:
            continue

        evidence_ids.append(str(experiment_id))
        evidence.append({
            "experiment": str(experiment_id),
            "observed_lost": lost,
            "root_cause": investigation.get("root_cause"),
            "fault": investigation.get("fault"),
            "target": investigation.get("target"),
            "summary": investigation.get("summary"),
        })

    if not evidence:
        return []

    # The LLM is optional. If unavailable, use a safe review-only fallback.
    try:
        data, _source = ask_json(
            "code_patch_suggestion",
            PATCH_SYSTEM,
            f"Measured experiment evidence:\n{evidence}",
            max_tokens=1200,
        )
    except Exception:
        data = None

    if isinstance(data, dict):
        title = data.get("title")
        why = data.get("why")
        diff = data.get("diff")

        if isinstance(title, str) and title.strip() and isinstance(why, str) and why.strip():
            # Accept a diff only if it resembles a unified diff.
            valid_diff = (
                isinstance(diff, str)
                and diff.strip()
                and "--- " in diff
                and "+++ " in diff
                and "@@ " in diff
            )

            return [{
                "id": "redis-retry-suggestion",
                "title": title.strip()[:160],
                "kind": "code_suggestion",
                "for": evidence_ids,
                "why": why.strip()[:1000],
                "diff": diff if valid_diff else None,
                "status": "proposed",
                "rpn": [],
            }]

    # Do not fabricate a diff when the LLM is unavailable.
    summary = "; ".join(
        f"{item['experiment']} observed {item['observed_lost']:g} lost item(s)"
        for item in evidence
    )

    return [{
        "id": "redis-retry-suggestion",
        "title": "Review Redis reconnect and retry handling",
        "kind": "code_suggestion",
        "for": evidence_ids,
        "why": (
            summary
            + ". Review the actual worker source before proposing a code diff."
        ),
        "diff": None,
        "status": "proposed",
        "rpn": [],
    }]
