"""Persistent evidence memory, preserving the Section 9.2 record formats.

Stores measured cases and explicitly reviewed fix outcomes in blueprint tables.
No Docker calls, model calls, or database writes happen on import.
"""
import json
import sqlite3
from pathlib import Path


DEFAULT_PATH = Path(__file__).resolve().parents[1] / "runs" / "knowledge.sqlite3"


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


class KnowledgeStore:
    """Use as a context manager; each save commits atomically."""

    def __init__(self, path=DEFAULT_PATH):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY, spec_json TEXT NOT NULL, run_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                experiment_id TEXT PRIMARY KEY, summary_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS signatures (
                id TEXT PRIMARY KEY, features_json TEXT NOT NULL,
                labels_json TEXT NOT NULL, confirmed INTEGER NOT NULL
                CHECK (confirmed IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS diagnoses (
                id TEXT PRIMARY KEY, json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fixes (
                id TEXT PRIMARY KEY, json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS verifications (
                fix_id TEXT PRIMARY KEY, json TEXT NOT NULL
            );
        ''')

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def save_experiment(self, spec, run_id):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO experiments VALUES (?, ?, ?)",
                (spec["id"], _json(spec), run_id))

    def save_observation(self, summary):
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO observations VALUES (?, ?)",
                (summary["experiment"], _json(summary)))

    def get_observation(self, experiment_id):
        row = self.connection.execute(
            "SELECT summary_json FROM observations WHERE experiment_id = ?",
            (experiment_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def clear_observation(self, experiment_id):
        """Remove an earlier case before reusing an experiment ID in a new run."""
        with self.connection:
            self.connection.execute("DELETE FROM observations WHERE experiment_id = ?", (experiment_id,))


    def save_diagnosis(self, diagnosis):
        """Store the complete Section 8.2 artifact, without renaming fields."""
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO diagnoses VALUES (?, ?)",
                (diagnosis["incident"], _json(diagnosis)))

    def get_diagnosis(self, incident):
        row = self.connection.execute(
            "SELECT json FROM diagnoses WHERE id = ?", (incident,)).fetchone()
        return json.loads(row[0]) if row else None

    def register_solution(self, signature_id, diagnosis, fix, verification, *, manual_confirmation=False):
        """Register reviewed Section 8.2 artifacts, never execute their changes.

        Links use existing fields: exact confirmed cause, fix.for -> incident,
        and verification.fix -> fix.id. No extra schema or synthetic seeding.
        """
        from .signatures import verified_improvement
        signatures = {s["id"]: s for s in self.signatures()}
        signature = signatures.get(signature_id)
        if manual_confirmation is not True or not signature:
            raise ValueError("manual confirmation and an existing confirmed signature are required")
        if not self.get_observation(signature["from"]):
            raise ValueError("source observation is missing")
        if diagnosis.get("root_cause") != signature["root_cause"] or not diagnosis.get("confirmed_by"):
            raise ValueError("diagnosis must match the confirmed cause and cite its confirmation")
        if fix.get("for") != diagnosis.get("incident") or verification.get("fix") != fix.get("id"):
            raise ValueError("diagnosis, fix and verification links do not match")
        if signature["from"] not in (fix.get("verification") or {}).get("rerun", []):
            raise ValueError("fix verification must reference the source experiment")
        if not verified_improvement(fix, verification):
            raise ValueError("verification must demonstrate the required improvement and be kept")
        required = {"incident", "root_cause", "symptoms", "differential", "evidence_for", "evidence_against",
                    "confirmed_by", "confidence", "would_change_mind"}
        if set(diagnosis) != required or set(fix) != {"id", "for", "layer", "change", "why", "expected",
                "verification", "code_patch", "approval"} or set(verification) != {
                    "fix", "runs", "before", "after", "regression", "decision"}:
            raise ValueError("artifacts must preserve the Section 8.2 fields")
        records = [("diagnoses", diagnosis["incident"], diagnosis), ("fixes", fix["id"], fix),
                   ("verifications", fix["id"], verification)]
        with self.connection:
            for table, identifier, artifact in records:
                key = "fix_id" if table == "verifications" else "id"
                old = self.connection.execute(f"SELECT json FROM {table} WHERE {key} = ?", (identifier,)).fetchone()
                if old and json.loads(old[0]) != artifact:
                    raise ValueError(f"{table} record already exists with different content")
                self.connection.execute(f"INSERT OR IGNORE INTO {table} VALUES (?, ?)", (identifier, _json(artifact)))

    def verified_solutions(self, signature):
        """Only solutions whose stored reports still demonstrate improvement."""
        from .signatures import verified_improvement
        solutions = []
        for row in self.connection.execute("SELECT json FROM fixes ORDER BY id").fetchall():
            fix = json.loads(row[0])
            diagnosis = self.get_diagnosis(fix.get("for"))
            report = self.connection.execute("SELECT json FROM verifications WHERE fix_id = ?", (fix["id"],)).fetchone()
            if not diagnosis or diagnosis.get("root_cause") != signature["root_cause"] or not diagnosis.get("confirmed_by"):
                continue
            if signature["from"] not in (fix.get("verification") or {}).get("rerun", []):
                continue
            verification = json.loads(report[0]) if report else {}
            if verified_improvement(fix, verification):
                solutions.append({"fix": fix, "verification": verification})
        return solutions

    def save_signature(self, signature):
        from .signatures import validate_signature
        validate_signature(signature)
        # labels_json retains every non-feature field for a lossless round trip.
        labels = {k: v for k, v in signature.items()
                  if k not in ("id", "features", "confirmed")}
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO signatures VALUES (?, ?, ?, ?)",
                (signature["id"], _json(signature["features"]),
                 _json(labels), int(signature["confirmed"])))

    def signatures(self, confirmed_only=True):
        query = "SELECT * FROM signatures"
        if confirmed_only:
            query += " WHERE confirmed = 1"
        rows = self.connection.execute(query + " ORDER BY id").fetchall()
        return [dict(json.loads(r["labels_json"]), id=r["id"],
                     features=json.loads(r["features_json"]),
                     confirmed=bool(r["confirmed"])) for r in rows]

    def similar_signatures(self, features, limit=3):
        from .signatures import find_similar
        return find_similar(features, self.signatures(), limit=limit)

    def confirm_case(self, signature, *, manual_confirmation=False):
        """Register an explicitly reviewed case against an existing observation.

        Confirmation is a human assertion, not an LLM-generated confidence score.
        Existing records cannot be silently replaced through this interface.
        """
        from .signatures import validate_signature
        validate_signature(signature)
        if manual_confirmation is not True or signature["confirmed"] is not True:
            raise ValueError("explicit manual confirmation and confirmed=true are required")
        observation = self.get_observation(signature["from"])
        if not observation or observation.get("experiment") != signature["from"]:
            raise ValueError("case must reference an existing matching observation")
        labels = {k: v for k, v in signature.items() if k not in ("id", "features", "confirmed")}
        with self.connection:
            existing = self.connection.execute("SELECT * FROM signatures WHERE id = ?", (signature["id"],)).fetchone()
            if existing:
                old = dict(json.loads(existing["labels_json"]), id=existing["id"],
                           features=json.loads(existing["features_json"]), confirmed=bool(existing["confirmed"]))
                if old != signature:
                    raise ValueError("signature ID already exists with different content; choose a new ID")
                return
            self.connection.execute("INSERT INTO signatures VALUES (?, ?, ?, ?)",
                (signature["id"], _json(signature["features"]), _json(labels), 1))

    def retrieve_cases(self, features, observation=None, *, exclude_experiment=None, limit=3):
        """Bounded internal RAG packet: confirmed cases plus recorded evidence.

        Exact normalized log matches supplement binary symptoms. Scores are not
        probabilities. A source observation is required; missing data stays null.
        No current-case self matches, writes, model calls or format changes.
        """
        from .signatures import _validate_features, error_templates, jaccard
        _validate_features(features)
        if type(limit) is not int or not 1 <= limit <= 3:
            raise ValueError("retrieval limit must be between 1 and 3")
        current_logs = error_templates(observation or {})
        matches = []
        for signature in self.signatures():
            source_id = signature["from"]
            if source_id == exclude_experiment:
                continue
            source = self.get_observation(source_id)
            if not source or source.get("experiment") != source_id:
                continue
            similarity = jaccard(features, signature["features"])
            source_logs = error_templates(source)
            # Match text across services, but retain each historical service name.
            patterns = {pattern for _, pattern in current_logs}
            logs = sorted((service, line) for (service, pattern), line in source_logs.items() if pattern in patterns)
            if similarity < 0.6 and not logs:
                continue
            matches.append({"signature": signature["id"], "from": source_id,
                "similarity": round(similarity, 3),
                "compared_features": sorted(features.keys() & signature["features"].keys()),
                "matched_log_count": len(logs), "fault": signature["fault"],
                "known_cause": signature["root_cause"][:300],
                "evidence": {"features": signature["features"],
                    "matching_logs": [{"service": service, "template": line[:240]} for service, line in logs[:2]],
                    "queue_depth": source.get("queue_depth"), "delivery": source.get("delivery"),
                    "mttd_s": source.get("mttd_s"), "mttr_s": source.get("mttr_s")},
                "verified_fixes": [{"id": solution["fix"]["id"],
                    "recommendation": str(solution["fix"]["why"])[:240],
                    "change": solution["fix"]["change"],
                    "verified_runs": solution["verification"]["runs"]}
                    for solution in self.verified_solutions(signature)[:2]],
                "limitation": "Manually confirmed historical case; matching symptoms or logs do not confirm this incident"})
        return sorted(matches, key=lambda m: (-m["matched_log_count"], -m["similarity"], m["signature"]))[:limit]


def load_observation(experiment_id):
    """Optional evidence must not prevent diagnosis when storage is unavailable."""
    if not DEFAULT_PATH.exists():
        return None
    try:
        with KnowledgeStore() as store:
            return store.get_observation(experiment_id)
    except (OSError, sqlite3.Error, ValueError):
        return None


def main():
    """Explicit case registration, separate from the orchestrator CLI."""
    import argparse
    parser = argparse.ArgumentParser(description="Register a manually reviewed Section 8.2 signature")
    parser.add_argument("signature_file", type=Path)
    parser.add_argument("--confirm", action="store_true", help="I reviewed the evidence and confirm the stated cause")
    parser.add_argument("--store", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--diagnosis-file", type=Path)
    parser.add_argument("--fix-file", type=Path)
    parser.add_argument("--verification-file", type=Path)
    args = parser.parse_args()
    if not args.confirm:
        parser.error("--confirm is required; model output alone is not confirmation")
    if not args.store.exists():
        parser.error("store does not exist; collect the observation before registering its signature")
    try:
        signature = json.loads(args.signature_file.read_text(encoding="utf-8-sig"))
        with KnowledgeStore(args.store) as store:
            files = (args.diagnosis_file, args.fix_file, args.verification_file)
            if any(files):
                if not all(files):
                    raise ValueError("solution registration requires all three artifact files")
                stored = next((s for s in store.signatures() if s["id"] == signature["id"]), None)
                if stored != signature:
                    raise ValueError("register the confirmed signature first; supplied signature must match storage")
                artifacts = [json.loads(path.read_text(encoding="utf-8-sig")) for path in files]
                store.register_solution(signature["id"], *artifacts, manual_confirmation=True)
            else:
                store.confirm_case(signature, manual_confirmation=True)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        parser.exit(1, f"Case not registered: {exc}\n")
    print(f"Registered reviewed {'solution for' if any(files) else 'signature'} {signature['id']}")


if __name__ == "__main__":
    main()
