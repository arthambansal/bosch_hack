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

CI is deliberately limited to one non-stateful kill/pause per scenario and uses a
fresh base sandbox. No netem success is claimed. The workflow fails explicitly when
there are no reviewed scenarios or an unsupported scenario; it cannot report an
empty suite as a successful live chaos test. Human-gated cases run locally.
