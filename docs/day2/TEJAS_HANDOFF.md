# Day 2 integration handoff for Artham

Tejas changes stay within the assigned file list; no state/schema, CLI, engine,
Governor, diagnosis, dashboard or teammate files were edited.

## CLI syntax (Artham-owned chaospilot.py)

The existing `cmd_replay` already runs all files by default and exits 1 on failure.
It accepts `--scenario` but not positional paths or `--all`. Until the change below
is merged, the workflow uses the existing `python chaospilot.py replay` spelling.

Add these parser arguments after the existing command argument:

```python
p.add_argument("replay_path", nargs="?", help="replay: one scenario path")
p.add_argument("--all", action="store_true", dest="all_scenarios", help="replay every saved scenario")
```

After `a = p.parse_args()` and before dispatch:

```python
if a.command != "replay" and (a.replay_path or a.all_scenarios):
    p.error("positional scenario and --all apply only to replay")
if a.command == "replay":
    if (a.replay_path and a.scenario) or (a.all_scenarios and (a.replay_path or a.scenario)):
        p.error("choose a positional path, --scenario, or --all")
    a.scenario = a.replay_path or a.scenario
```

In cmd_replay, exclude .status.json from the glob for portability:

```python
paths = ([a.scenario] if a.scenario else sorted(
    path for path in glob.glob(os.path.join(ROOT, "scenarios", "*.json"))
    if not os.path.basename(path).startswith(".")))
```

Then the workflow may switch to `python chaospilot.py replay --all`.
No CLI patch is applied by Tejas.

## Wiring already implemented inside Reporter

Reporter calls export_scenario for each result with its investigation, publishes
live_state.regression, and adds the v2 sections to both report formats. No new graph
state keys are introduced. Existing engine impact_of calls now compute the values.
Mystery counts read runs/mystery_trials.jsonl; fix verdicts use verification.fix_status.
Rolled-back per-fix RPN comes from current-run published fixes when available; if
metadata is absent it stays Not available, never guessed from unrelated rows.

## Outstanding evidence / decisions

- Supply raw auto_20261010_153557 and auto_20261010_170117 results, investigations,
  verification, FMEA and events; assignment numbers alone are not measurement files.
- Supply the golden run, recording and public video URL.
- Supply official submission URL, required member details and form instructions.
- CI has not been observed running. Empty/no approved unattended scenarios fails
  explicitly. Combined/data-store replays retain the human gate; do not weaken it
  to obtain a green CI check. Agree a separately scoped CI policy if those cases
  must be unattended.
- Governor policy_check reads process-global cfg; replay locally enforces the same
  documented one/two-fault, sandbox-target, one-data-store limits using its cfg,
  before constructing Engine. A future shared pure policy helper belongs to Artham.
