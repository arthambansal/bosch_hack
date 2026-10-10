"""Persistent evidence memory, preserving the Section 9.2 record formats.

This first module implements the four tables needed for signature retrieval.
Other owners can add their storage interfaces once their contracts are agreed.
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


def load_observation(experiment_id):
    """Optional evidence must not prevent diagnosis when storage is unavailable."""
    if not DEFAULT_PATH.exists():
        return None
    try:
        with KnowledgeStore() as store:
            return store.get_observation(experiment_id)
    except (OSError, sqlite3.Error, ValueError):
        return None
