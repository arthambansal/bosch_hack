# Never-again scenarios

Reporter exports confirmed failures with two to four investigation evidence lines.
No fabricated scenario is shipped as a measured result. The locally preserved E1 run
recovered without loss or stuck services, so it does not qualify for export.

Each JSON file contains id, name, steps, invariants, from_run and evidence. Review it
before committing. Export never overwrites the first record for an id. JSON status
is local in .status.json and is excluded from Git.

On the base sandbox, a confirmed weakness is expected to FAIL its invariant checks.
After a separately approved fix, replay the same file and require PASS; the engine
never applies fixes itself. Missing measurements and incomplete injection fail closed.
Every replay also requires measured HTTP recovery. A non-recovery export has no
invented deadline: no_stuck_services plus that mandatory recovery check is used.
A measured recovery deadline is relative to restoration, matching recovery_s.

Current commands: `python chaospilot.py replay --scenario scenarios/<id>.json` or
`python chaospilot.py replay` for all. Data-store disruption and combined scenarios
require the existing human gate. STOP is retained, never cleared by replay.

CI selects only single worker/result kill or pause scenarios and uses a fresh base
sandbox. Combined and data-store scenarios remain available for local, human-approved
replay and are skipped by CI. The workflow fails explicitly when no reviewed CI-safe
scenario exists; it cannot report an empty suite as successful. The workflow is
manual (`workflow_dispatch`) because live runner behavior is not yet verified.
The measured `result-pause-ci.json` scenario recovered in 0.6s with 32/32 votes
delivered and no stuck items. No netem success is claimed.

To produce the first eligible scenario from a real measurement, start/map/baseline
the sandbox and run `python docs/measure_ci_scenario.py`. It runs one `pause result`
experiment through the production Engine and writes `result-pause-ci.json` only when
recovery is measured, recorded loss is zero, and no service remains stuck. Raw
results and events stay in `runs/ci_measure_*` for review.
