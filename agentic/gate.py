"""HUMAN GATE (deterministic code, no AI). Owner: Artham. Contract: CONTRACT.md "Human approval and STOP".

One gate = one question to a human, with its own UNIQUE token (gate_id) and an expiry time.

  orchestrator publishes   live_state.approval_request = {gate_id, id, name, reason, steps, created_at, expires_at, timeout_s}
  dashboard / Discord      POST /approve {gate_id, approved: true|false}  -> server checks gate_id == the pending one and that
                           it has not expired, then writes runs/approval.json ATOMICALLY (temp file + os.replace):
                           {"gate_id": "...", "approved": true|false, "by": "dashboard"|"discord", "submitted_at": epoch}
  orchestrator             accepts ONLY a decision whose gate_id matches; the first valid one wins, the file is removed,
                           and live_state.approval_result = {gate_id, answer, source, at} is published.
  terminal                 "y"/"n" also works (read by a background thread, so it works on Windows too).
  no answer before expires_at, or a STOP file  ->  denied (safe default).

Why the old version lost decisions: it published the request first and deleted approval.json afterwards, so a fast click
was erased. Now stale files are removed BEFORE the request is published and nothing is deleted after that, except a
decision we have just consumed.
"""
import json
import os
import queue
import sys
import threading
import time
import uuid

from core.common import LIVE, RUNS_DIR, STOP_FILE

APPROVAL_FILE = os.path.join(RUNS_DIR, "approval.json")
DEFAULT_TIMEOUT_S = 180
POLL_S = 0.3

_stdin_lines = queue.Queue()
_reader = {"started": False}
_pause = threading.Event()          # never set: _pause.wait(x) is a plain sleep that tests cannot monkeypatch away


def _stdin_reader():
    try:
        for line in sys.stdin:
            _stdin_lines.put(line.strip())
    except Exception:  # noqa: BLE001 - stdin may be closed or replaced (tests, services): then terminal answers are off
        pass


def _poll_terminal():
    """Terminal answers without select.select() (which does not work on Windows stdin): a daemon thread feeds a queue."""
    if not _reader["started"]:
        _reader["started"] = True
        threading.Thread(target=_stdin_reader, daemon=True).start()
    try:
        return _stdin_lines.get_nowait()
    except queue.Empty:
        return None


def _drain_terminal():
    while True:
        try:
            _stdin_lines.get_nowait()
        except queue.Empty:
            return


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def read_answer(path):
    """Old format without a gate token: {"approved": true|false} or {"answer": "yes"}. Kept for the legacy tests/Discord."""
    data = json.load(open(path))
    if "approved" in data:
        return "yes" if data["approved"] is True else "no"
    return str(data.get("answer", "no"))


def read_decision(path, gate):
    """Return 'yes' / 'no' for a decision that belongs to THIS gate, else None (no file, half-written, or stale)."""
    try:
        data = json.load(open(path))
        mtime = os.path.getmtime(path)
    except (OSError, ValueError):
        return None                                   # missing or still being written: look again
    if not isinstance(data, dict):
        return None
    if "gate_id" in data:
        if data["gate_id"] != gate["gate_id"]:
            return None                               # decision for another / older gate: ignore
    elif mtime < gate["created_at"]:
        return None                                   # legacy file without a token that is older than the request: stale
    if "approved" in data:
        return "yes" if data["approved"] is True else "no"
    if "answer" in data:
        return str(data["answer"])
    return None


def ask_human(req, timeout_s=DEFAULT_TIMEOUT_S):
    """Ask one question. Returns the answer text ('yes', 'no', or whatever was typed). Always clears approval_request."""
    now = time.time()
    gate = {"gate_id": uuid.uuid4().hex[:12], "id": req.get("id"), "name": req.get("name"),
            "question": req.get("question"), "reason": req.get("reason"), "steps": req.get("steps"),
            "created_at": now, "expires_at": now + timeout_s, "timeout_s": timeout_s}
    _remove(APPROVAL_FILE)                            # old decisions can never apply to this gate
    _drain_terminal()
    LIVE.set(agent_active="human", approval_request=gate, approval_result=None)   # visible BEFORE we wait
    print(f"\n>>> HUMAN APPROVAL NEEDED [{gate['gate_id']}]: {req['question']}\n    why: {req.get('reason')}\n"
          f"    type y or n (or use the dashboard, {timeout_s}s): ", end="", flush=True)
    answer, source = "no", "timeout"
    try:
        while time.time() < gate["expires_at"]:
            if os.path.exists(STOP_FILE):
                print("(STOP requested, denied)")
                answer, source = "no", "stop"
                break
            decision = read_decision(APPROVAL_FILE, gate)
            if decision is not None:
                _remove(APPROVAL_FILE)                # consumed: a duplicate submit can no longer be applied
                answer, source = decision, "dashboard"
                break
            line = _poll_terminal()
            if line is not None:
                answer, source = line, "terminal"
                break
            _pause.wait(POLL_S)
        else:
            print("(no answer, denied)")
    finally:
        approved = str(answer).strip().lower() in ("y", "yes", "approve", "approved", "true")
        LIVE.set(approval_request=None, agent_active=None,
                 approval_result={"gate_id": gate["gate_id"], "answer": "approved" if approved else "denied",
                                  "source": source, "at": time.time()})
    return answer
