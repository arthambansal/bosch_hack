"""Section 8.2 failure signatures and Jaccard retrieval over known symptoms.

Unknown features are omitted, never silently converted into healthy zeros.
Fault identity and confirmation must be supplied by the governed caller.
"""
FEATURES = frozenset(("entry_errors", "read_errors", "queue_growth", "db_stall",
                      "consumer_exit", "new_dns_error", "recovers"))
FIELDS = {"id", "from", "fault", "features", "root_cause", "confirmed"}


def _validate_features(features):
    if not isinstance(features, dict) or set(features) - FEATURES:
        raise ValueError("features must use the Section 8.2 feature names")
    if any(type(v) is not int or v not in (0, 1) for v in features.values()):
        raise ValueError("known features must be integer 0 or 1; omit unknowns")


def validate_signature(signature):
    if set(signature) != FIELDS:
        raise ValueError("signature fields must match Section 8.2")
    if set(signature["fault"]) != {"type", "target_role"}:
        raise ValueError("fault requires type and target_role")
    for value in (signature["id"], signature["from"],
                  signature["fault"]["type"], signature["fault"]["target_role"]):
        if not isinstance(value, str) or not value:
            raise ValueError("signature identifiers and fault labels must be nonempty strings")
    if not isinstance(signature["root_cause"], str):
        raise ValueError("root_cause must be a string")
    if type(signature["confirmed"]) is not bool:
        raise ValueError("confirmed must be boolean")
    if signature["confirmed"] and not signature["root_cause"].strip():
        raise ValueError("a confirmed signature needs a root cause")
    _validate_features(signature["features"])


def extract_features(observation):
    """Extract only directly supported features from an Observer summary.

    db_stall and consumer_exit require evidence beyond this summary's basic
    counters/service names. Supply those via evidence_features when available.
    """
    features = {}
    rates = observation.get("probe_error_rate") or {}
    for probe, feature in (("vote_write", "entry_errors"), ("result_page", "read_errors")):
        rate = rates.get(probe)
        if isinstance(rate, (int, float)) and not isinstance(rate, bool) and 0 <= rate <= 1:
            features[feature] = int(rate > 0)
    depth = observation.get("queue_depth") or {}
    start, end = depth.get("start"), depth.get("end")
    if all(isinstance(v, (int, float)) and not isinstance(v, bool)
           and v >= 0 for v in (start, end)):
        features["queue_growth"] = int(end > start)
    # A present null MTTR explicitly means no recovery; an absent field is unknown.
    if "mttr_s" in observation:
        recovery = observation["mttr_s"]
        if recovery is None:
            features["recovers"] = 0
        elif isinstance(recovery, (int, float)) and not isinstance(recovery, bool) and recovery >= 0:
            features["recovers"] = 1
    templates = observation.get("new_log_templates") or {}
    text = " ".join(str(line) for lines in templates.values() for line in lines).lower()
    if any(marker in text for marker in
           ("name or service not known", "getaddrinfo", "enotfound", "dns lookup")):
        features["new_dns_error"] = 1
    return features


def build_signature(observation, *, signature_id, fault, root_cause="",
                    confirmed=False, evidence_features=None):
    """Caller explicitly supplies measured mechanism/role evidence and labels."""
    features = extract_features(observation)
    if evidence_features is not None:
        _validate_features(evidence_features)
        for key, value in evidence_features.items():
            if key in features and features[key] != value:
                raise ValueError(f"conflicting evidence for {key}")
            features[key] = value
    signature = {"id": signature_id, "from": observation["experiment"],
                 "fault": dict(fault), "features": features,
                 "root_cause": root_cause, "confirmed": confirmed}
    validate_signature(signature)
    return signature


def jaccard(left, right):
    """Compare active symptoms only where BOTH cases have measurements.

    No shared positive evidence returns zero, including two empty vectors.
    Similarity is retrieval evidence, not a probability or confirmation.
    """
    _validate_features(left)
    _validate_features(right)
    known = left.keys() & right.keys()
    a = {k for k in known if left[k] == 1}
    b = {k for k in known if right[k] == 1}
    return len(a & b) / len(a | b) if a | b else 0.0


def find_similar(features, signatures, limit=3):
    _validate_features(features)
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    matches = []
    for signature in signatures:
        validate_signature(signature)
        if signature["confirmed"]:
            matches.append({"signature": signature,
                            "similarity": jaccard(features, signature["features"]),
                            "compared_features": sorted(features.keys() & signature["features"].keys())})
    return sorted(matches, key=lambda m: (-m["similarity"], m["signature"]["id"]))[:limit]
