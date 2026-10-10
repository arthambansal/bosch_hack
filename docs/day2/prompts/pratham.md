# Prompt for Pratham's assistant: Truth Oracle and code-patch suggestions

You are my coding partner for the final day of a hackathon (Bosch, "AI-driven chaos engineering for cloud-native
resilience"). Our product is ChaosPilot: a multi-agent system that maps the Docker Example Voting App
(vote -> redis -> worker -> postgres -> result), plans and injects safe faults, diagnoses root causes, applies and
verifies fixes, and reports an FMEA risk score. Judging is Sunday 16:00. Today we add our differentiators.

FIRST, read these files in the repo, in this order, before writing any code:
1. docs/day2/DAY2_CONTRACT.md   (the binding contract: shapes, signatures, file ownership, rules)
2. CONTRACT.md                   (Day 1 contract: results.json, live_state, approval gate)
3. core/contract_v5.py           (validators for every new live_state shape)
4. tests/test_contract_v5.py and tests/test_graph_mock.py
5. The files listed under "Your files" below, and any file they import.

NON-NEGOTIABLE RULES
- Edit ONLY the files listed under "Your files". If you think another file must change, stop and write me the exact
  change so I can ask its owner. Never change a function signature from DAY2_CONTRACT.md section 5.
- The repo is public: never write API keys, webhook URLs or .env files. Secrets come only from environment variables.
- Faults only ever touch the sandbox containers from config.json. Safety logic stays deterministic code.
- Every new function needs a safe fallback: on any error it logs one LIVE.event("warn", ...) line and returns the
  "not available" value from the contract. It must never crash a run.
- No invented numbers. Anything shown to users comes from a measurement, or is shown as null / "not available".
- Write a test file that runs WITHOUT Docker or network (monkeypatch core.common.docker, requests, core.llm.ask_json).
  It prints "PASS ..." lines and ends with "ALL CHECKS PASSED".
- Before you say you are done, run and show the output of:
    PYTHONPATH=. python3 tests/test_contract_v5.py
    PYTHONPATH=. python3 tests/test_graph_mock.py
    PYTHONPATH=. python3 <your new test file>
  All three must end with ALL CHECKS PASSED.
- Keep code simple and readable; comments explain WHY. Python 3.10+, standard library + requests only (no new
  dependencies unless I approve).

WHEN YOU FINISH, give me: (1) a short list of files changed, (2) how to run the feature for real, (3) what I should say
to a judge about it in two sentences, (4) anything you could not finish or verify.

## My role
I own the Remediator agent and the Observer (probes, canaries, docker events).

## Your files
core/truth.py, core/probes.py, core/observer.py, core/heal.py, core/patches.py, sandbox/patches/* (new),
sandbox/fixes/*, agentic/nodes/remediator.py, tests/test_truth.py (new), tests/test_patches.py (new)

## Tasks, in priority order

### 1. Truth Oracle (core/truth.py) — contract 4.1 and 5. This is the opening moment of our demo.
Idea: health checks only ask "did the page answer?". The truth is "did the vote reach the database?". When probes
are green but votes stop arriving, that is a GRAY FAILURE (Microsoft Research term, HotOS 2017).
- `start()` launches a daemon thread. Every `interval_s` seconds it launches ONE canary in its own short-lived thread
  (so a slow canary never blocks the next) using the existing core.observer.trace_canary(cfg, timeout_s=grace_s).
  Keep a thread-safe record per canary: sent_at, status, lag.
- Counts: sent, stored (delivered True), pending (accepted, younger than grace_s, not yet seen), suspected_lost
  (accepted and not seen after grace_s). A request that failed (vote page down) is NOT a lost vote: count it separately
  and show it in the every_vote_counted detail text. last_lag_s = lag of the latest stored canary.
- Invariants (each {name, ok, detail}, ok null when it cannot be measured):
  - every_vote_counted: ok false if any canary is suspected_lost in the last 60 s.
  - worker_running: `docker inspect -f {{.State.Status}} <worker container>` == "running"; detail includes the exit
    code when exited (use .State.ExitCode). Use config.json services, never hard-code container names.
  - queue_drains: core.probes.backlog(cfg) sampled each tick; ok false if it grew on 3 consecutive samples.
- monitoring = "healthy" if every probe's recent error_rate (prober.snapshot()) < cfg["safety"]["max_error_rate"],
  "degraded" otherwise, "unknown" without a prober.
- status and diverged_at exactly as contract 4.1. `snapshot()` must pass core.contract_v5.validate_truth.
- `window(t_start, t_end)`: counts for canaries sent in that window plus diverged True/False.
- Must never raise; on errors keep the last good snapshot and set the affected invariant ok to null.
- Canary votes have ids starting "canary-". config.json now excludes them from the delivery count; check nothing in
  probes.py or observer.py counts them as normal votes.

### 2. Code-patch suggestion (core/patches.py + sandbox/patches/) — contract 4.4 and 6
- Read the worker source (sandbox/app-src, or clone dockersamples/example-voting-app at the commit in
  docs/FINDINGS.md). Known weakness: worker/Program.cs resolves the Redis host once (GetIp before the retry loop),
  the retry only catches RedisConnectionException, and Main's catch(Exception) returns exit code 1.
- Hand-write a small, reviewed unified diff in sandbox/patches/worker-redis-retry.diff: re-resolve the Redis host
  inside the retry loop and retry with backoff on DNS/socket errors instead of exiting. Verify it applies with
  `git apply --check` against the source. Also write a short README in sandbox/patches/ explaining it.
- `suggest_patches(investigations, results)` returns the entry {id: "worker-redis-retry", kind: "code_suggestion",
  status: "proposed", diff: <file text>, for: [experiment ids whose diagnosis or stuck_services mention the worker /
  DNS / exit code 1], ...} only when that evidence exists; otherwise []. Never applied automatically.

### 3. Fix entries and E3 (core/heal.py)
- Implement `fix_entries(fixes)` properly (title in plain English, why with numbers, the compose diff text built from
  the override file in sandbox/fixes/). Shape 4.4, status "applied".
- Investigate why E3 (kill Postgres) got WORSE after the fixes yesterday (RPN 630 -> 700): read the run folder
  runs/auto_20261010_170117 (results.json, verification.json, events.log) and write the explanation into
  docs/day2/E3_ANALYSIS.md. If a catalog fix is the cause, say so; Artham's verifier will now roll back fixes that
  make things worse.

### 4. Live check of all 5 fault types (Sunday 09:00–10:30, you own the sandbox)
The brief needs at least 3 failure types; we claim 5. Kill, pause, partition and latency have run live; the traffic
SPIKE never has. Run each type once for real with `python chaospilot.py run --only <id>` (or a one-step plan) and write
docs/day2/FAULT_TYPES.md: for each type the command, what was injected, the measured effect (error rate, p95, recovery
time, stuck services) and the run folder. If a type does not work (e.g. netem image missing), fix it in your files or
tell Artham immediately; never claim a type that did not run.

## Tests
tests/test_truth.py: fake trace_canary/docker/prober; check counts, grace logic, failed-request vs lost, each
invariant, status rules (ok / down / diverged / unknown), diverged_at set once and cleared on recovery, window(),
and validate_truth == [] for every snapshot. tests/test_patches.py: suggestion appears only with evidence, is always
"proposed", the diff file exists and passes validate_fixes.
