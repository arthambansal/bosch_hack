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

from contextlib import contextmanager

from core.common import LIVE, LIVE_FILE, RUNS_DIR, STOP_FILE

APPROVAL_FILE = os.path.join(RUNS_DIR, "approval.json")
LOCK_DIR = os.path.join(RUNS_DIR, "gate.lock")     # shared lock: a directory, because mkdir is atomic on Linux, macOS AND Windows
LOCK_STALE_S = 10                                  # a lock older than this was left by a crashed process: break it
LOCK_WAIT_S = 5
GATE_SYNC = {"version": 1, "lock": "runs/gate.lock", "submit": "agentic.gate.submit_decision"}
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


class GateLockTimeout(Exception):
    pass


@contextmanager
def gate_lock(timeout=LOCK_WAIT_S, lock_dir=None):
    """Cross-process mutex for the gate. The orchestrator takes it to OPEN, CONSUME and CLOSE a gate; the dashboard server
    takes it (through submit_decision) to validate and write a decision. So a decision can never be written into a gate that
    is being closed, nor consumed twice, nor wiped by the next gate opening."""
    lock_dir = lock_dir or LOCK_DIR
    deadline = time.time() + timeout
    while True:
        try:
            os.mkdir(lock_dir)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock_dir) > LOCK_STALE_S:
                    os.rmdir(lock_dir)               # stale lock from a crashed process
                    continue
            except OSError:
                pass
            if time.time() >= deadline:
                raise GateLockTimeout("gate lock busy")
            time.sleep(0.02)
    try:
        yield
    finally:
        try:
            os.rmdir(lock_dir)
        except OSError:
            pass


def _write_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def submit_decision(gate_id, approved, by="dashboard", live_file=None, approval_file=None, lock_dir=None):
    """For the dashboard / Discord server. Validates and records one decision. Returns (http_status, body).
    200 {"ok": true, "gate_id"}  |  409 {"error": "no_pending"|"stale"|"expired"|"already_decided"}  |  503 {"error": "gate_sync_unavailable"}"""
    live_file, approval_file = live_file or LIVE_FILE, approval_file or APPROVAL_FILE
    if not isinstance(approved, bool):
        return 400, {"error": "approved_must_be_boolean"}
    try:
        with gate_lock(lock_dir=lock_dir):
            try:
                with open(live_file) as f:
                    req = (json.load(f) or {}).get("approval_request")
            except (OSError, ValueError):
                req = None
            if not req:
                return 409, {"error": "no_pending"}
            if req.get("gate_id") != gate_id:
                return 409, {"error": "stale"}
            if time.time() >= req.get("expires_at", 0):
                return 409, {"error": "expired"}
            if os.path.exists(approval_file):
                return 409, {"error": "already_decided"}
            _write_json_atomic(approval_file, {"gate_id": gate_id, "approved": approved, "by": by, "submitted_at": time.time()})
            return 200, {"ok": True, "gate_id": gate_id}
    except GateLockTimeout:
        return 503, {"error": "gate_sync_unavailable"}


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def read_answer(path):
    """Old format without a gate token: {"approved": true|false} or {"answer": "yes"}. Kept for the legacy tests/Discord."""
    with open(path) as f:
        data = json.load(f)
    if "approved" in data:
        return "yes" if data["approved"] is True else "no"
    return str(data.get("answer", "no"))


def read_decision(path, gate):
    """Return 'yes' / 'no' for a decision that belongs to THIS gate, else None (no file, half-written, or stale)."""
    try:
        with open(path) as f:
            data = json.load(f)
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
    _drain_terminal()
    with gate_lock():                                 # OPEN: wipe old decisions and publish the request as one atomic step
        _remove(APPROVAL_FILE)
        LIVE.set(agent_active="human", approval_request=gate, approval_result=None, gate_sync=GATE_SYNC)
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
                with gate_lock():                     # CONSUME: re-check and remove under the lock, so it is used exactly once
                    decision = read_decision(APPROVAL_FILE, gate)
                    if decision is not None:
                        _remove(APPROVAL_FILE)
                if decision is not None:
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
        result = {"gate_id": gate["gate_id"], "answer": "approved" if approved else "denied", "source": source, "at": time.time()}
        try:
            with gate_lock():                         # CLOSE: after this a late submit gets 409 no_pending
                _remove(APPROVAL_FILE)
                LIVE.set(approval_request=None, agent_active=None, approval_result=result)
        except GateLockTimeout:                       # never leave a gate open: close without the lock if it is stuck
            _remove(APPROVAL_FILE)
            LIVE.set(approval_request=None, agent_active=None, approval_result=result)
    return answer
