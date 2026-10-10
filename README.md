# ChaosPilot

A governed chaos-engineering sandbox for the Docker Example Voting App. Reasoning agents map risks, plan experiments, diagnose symptoms and recommend fixes; deterministic code injects faults, watches thresholds and computes FMEA scores.

## Tejas implementation

- Source tools: `core/code_tools.py` exposes bounded `list_files`, numbered `read_file` and literal `grep`, confined to `sandbox/app-src`. Resolved escapes and `.git` paths are rejected; tools never write or execute source.
- Cartographer: source-aware ReAct tools plus a deterministic W1 fallback citing `worker/Program.cs`, `GetIp`, `OpenRedisConnection` and `Main`. Section 8.2 Hypothesis records are saved to `runs/cartographer_hypotheses.json`; the existing `threat_model` state fields remain unchanged. Hypotheses remain open until supported by intervention evidence.
- Reporter: evidence-selected AI executive summary with deterministic fallback, Observer MTTD/MTTR with sample coverage, separately labelled HTTP timings, an OR fault tree and a service × fault heatmap. Writes `report.md` and escaped `report.html`.
- Deliverables: `docs/ARCHITECTURE.md`, `docs/FINDINGS.md`, `docs/TEAM_FORM.md`, `docs/VIDEO_SCRIPT.md` and the captioned evidence video packaged with this handoff.

## Setup in a fresh directory

```powershell
git clone https://github.com/arthambansal/bosch_hack.git
cd bosch_hack
git checkout tejas
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
git clone https://github.com/dockersamples/example-voting-app sandbox/app-src
.\.venv\Scripts\python.exe tests/test_graph_mock.py
.\.venv\Scripts\python.exe docs/test_tejas.py
```

Python 3.11+ and Docker Compose are required. On POSIX use `.venv/bin/python` instead. Source is ignored by the existing `.gitignore`; never commit application-source clones, secrets, virtual environments or generated runs.

## Real sandbox validation

Check that existing `chaos-*` containers and network `chaosnet` are not someone else's work before starting:

```powershell
docker compose -f sandbox/docker-compose.yml up -d
.\.venv\Scripts\python.exe chaospilot.py map
.\.venv\Scripts\python.exe chaospilot.py baseline --seconds 30
```

After a human explicitly approves **one Redis kill**, run:

```powershell
.\.venv\Scripts\python.exe docs/validate_e1.py --human-approved-e1
```

This harness selects only `kill:redis`, checks the existing Governor, records the approval, then invokes the production Cartographer, Executor, evaluator and Reporter. It keeps the existing runtime kill switch and restoration, applies no fixes and does not select combined faults. The flag records approval already given; it is not a substitute for asking a human. Review `runs/<run>/results.json`, `events.log`, `approval_evidence.json`, `final_state.json`, `report.md` and `report.html`.

For the full graph use `chaospilot.py autopilot --approve --no-heal --max 3`. **Current upstream limitations:** Windows terminal approval uses `select()` on stdin and fails with WinError 10038. The upstream Governor requests human approval for combined faults only, rather than all data-store kills; obtain approval externally before those tests. `--max 1` fallback selects a combined experiment rather than a single Redis kill. These are Artham-owned integration issues; they are not patched here. The standalone `report` command is retired; the Reporter node or validation harness writes reports.

Set API configuration through environment variables as documented in `core/llm.py`; never commit values. No LLM key was available in this validation, so rule fallbacks were tested. `--offline` replays caches when available and otherwise uses fallback.

## Evidence and limits

On 10 Oct 2026 the 15-second real baseline delivered 31/31 votes. The approved Redis-kill test triggered the kill switch after 4.5 seconds, had 0.5-second first HTTP error and 1.5-second HTTP recovery after restoration, and recorded 24/24 delivered votes. W1 was **not reproduced**; no worker was reported stuck. These are one-laptop, one-trial observations. No fix was applied or verified. Observer timestamps, canary tracing, second-laptop checks and mystery-fault trials were not supplied. End-to-end MTTD/MTTR therefore remain unknown. See `docs/FINDINGS.md` for raw evidence and exact limitations.

Every change must respect `docs/PROJECT_BLUEPRINT.md` Sections 8, 9 and 20.2. Before every push, `tests/test_graph_mock.py` must print **ALL CHECKS PASSED**. Tejas edits only his nodes, `core/code_tools.py`, `core/report_extras.py`, README and docs. `core/agents.py` is already absent at the inspected base revision; Dipen's migration and all state/schema files remain untouched.
