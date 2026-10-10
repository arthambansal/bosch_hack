#!/usr/bin/env python3
"""ChaosPilot CLI - the single entry point.

  python chaospilot.py up                 start the sandbox app (docker compose)
  python chaospilot.py map                auto-discover dependencies -> dependencies.json
  python chaospilot.py baseline           30s of steady traffic -> baseline.json
  python chaospilot.py plan               AI ranks experiments -> plan.json   (--offline = replay cache)
  python chaospilot.py run                run the plan with kill switch       (--only E1,E2)
  python chaospilot.py agent              AUTONOMOUS agent: AI picks each next attack after seeing results
  python chaospilot.py autopilot          MULTI-AGENT run (LangGraph): cartographer -> experimenter -> governor -> execute
                                          -> investigator -> ... -> remediator -> verify -> reporter
                                          [--goal "what if redis dies during a spike?"] [--approve] [--no-heal]
  python chaospilot.py graph              print the agent graph as a Mermaid diagram (docs/agent_graph.md)
  python chaospilot.py report             score + AI post-mortem              (--compare <old run dir>)
  python chaospilot.py dashboard          live dashboard on http://localhost:8000
  python chaospilot.py heal               FMEA -> pick fixes -> apply -> re-run -> prove RPN dropped
  python chaospilot.py mystery            hidden fault, blind diagnosis, reveal   (--wait = judge mode, --trials N, --choice M-kill-redis)
  python chaospilot.py replay             re-run saved never-again scenarios      (--scenario scenarios/<id>.json)
  python chaospilot.py panic              restore every container, no questions asked
  python chaospilot.py demo               map -> baseline -> plan -> run -> report
"""
import argparse
import os
import subprocess
import sys

from core.common import (BASELINE_FILE, DEPS_FILE, PLAN_FILE, ROOT, LIVE, latest_run_dir, load_config,
                         load_json)

COMPOSE = ["docker", "compose", "-f", os.path.join(ROOT, "sandbox", "docker-compose.yml")]


def need(path, hint):
    data = load_json(path)
    if not data:
        sys.exit(f"Missing {os.path.basename(path)}. Run: python chaospilot.py {hint}")
    return data


def cmd_up(a, cfg):
    extra = [x for f in (a.fix or []) for x in ("-f", os.path.join(ROOT, "sandbox", "fixes", f))]
    subprocess.run(COMPOSE[:3] + [COMPOSE[3]] + extra + ["up", "-d"], check=False)
    subprocess.run(["docker", "pull", cfg["fault_params"]["netem_image"]], check=False)  # for latency fault
    print("Sandbox starting. Vote page: http://localhost:8080  Results: http://localhost:8081")


def cmd_map(a, cfg):
    from core.discover import discover
    discover(cfg)


def cmd_baseline(a, cfg):
    from core.engine import Engine
    Engine(cfg, need(DEPS_FILE, "map")).baseline(seconds=a.seconds)


def cmd_plan(a, cfg):
    from core.planner import build_plan
    build_plan(cfg, need(DEPS_FILE, "map"), load_json(BASELINE_FILE), offline=a.offline)


def cmd_run(a, cfg):
    from core.engine import Engine
    plan = need(PLAN_FILE, "plan")
    eng = Engine(cfg, need(DEPS_FILE, "map"))
    run_dir, _ = eng.run(plan, only=a.only.split(",") if a.only else None)
    print(f"\nNext: python chaospilot.py report   (run folder: {run_dir})")


def cmd_agent(a, cfg):
    from core.agent import Agent
    from core.engine import Engine
    graph, base = need(DEPS_FILE, "map"), load_json(BASELINE_FILE, {})
    eng = Engine(cfg, graph)
    run_dir, _ = eng.run_agent(Agent(cfg, graph, base, offline=a.offline), max_steps=cfg.get("max_experiments", 6))
    print(f"\nNext: python chaospilot.py report   (run folder: {run_dir})")


def cmd_autopilot(a, cfg):
    from agentic import runtime
    from agentic.graph import run
    if a.max:
        cfg["max_experiments"] = a.max
    runtime.RT["cfg"] = cfg
    final = run(goal=a.goal or "", require_approval=a.approve, offline=a.offline, heal=not a.no_heal)
    rep = final.get("report") or {}
    print(f"\nResilience score: {rep.get('resilience_score')}/100 (grade {rep.get('grade')})"
          + (f" -> after fixes {rep.get('after')}/100" if rep.get("after") is not None else ""))
    if rep.get("fix_table"):
        print("\n" + rep["fix_table"])
    print(f"\nReport: {rep.get('path_md')}")


def cmd_graph(a, cfg):
    from agentic.graph import mermaid
    text = mermaid()
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "agent_graph.md"), "w") as f:
        f.write("```mermaid\n" + text + "\n```\n")
    print(text)


def cmd_report(a, cfg):
    try:
        from core.report import build_report
    except ImportError:
        sys.exit("The standalone report command is retired. Run `python3 chaospilot.py autopilot`: "
                 "the Reporter agent writes runs/<run>/report.md at the end.")
    run_dir = a.run_dir or latest_run_dir() or sys.exit("No run found. Run: python chaospilot.py run")
    LIVE.set(phase="reporting")
    build_report(run_dir, compare_dir=a.compare, offline=a.offline)
    LIVE.set(phase="ran")
    print(f"Report written to {run_dir}/report.md")


def cmd_heal(a, cfg):
    """The closed loop: break -> FMEA -> fix from safe catalog -> re-run the bad experiments -> re-score."""
    import time
    from core.engine import Engine
    from core.fmea import build_fmea, compare_fmea, format_table
    from core.heal import advise_fixes, apply_fixes
    from core.common import save_json
    graph, plan = need(DEPS_FILE, "map"), need(PLAN_FILE, "plan")
    before_dir = a.run_dir or latest_run_dir() or sys.exit("No run found. Run: python chaospilot.py run")
    results = load_json(os.path.join(before_dir, "results.json"), [])
    base = load_json(BASELINE_FILE, {})
    before = build_fmea(results, base)
    print(format_table(before))
    fixes, extras, source = advise_fixes(before, results, graph, offline=a.offline)
    if not fixes:
        sys.exit("No High/Medium priority findings with a catalog fix. Nothing to heal.")
    for f in fixes:
        LIVE.event("ai", f"FIX [{source}] {f['id']} (for {', '.join(f['rows'])}): {f['why']}")
    for e in extras:
        LIVE.event("ai", f"ALSO RECOMMENDED (manual, not auto-applied): {e.get('problem')} -> {e.get('recommendation')}")
    LIVE.set(phase="healing")
    if not apply_fixes(fixes, cfg):
        sys.exit("docker compose could not apply the fixes")
    time.sleep(12)   # let recreated containers come up
    ids = sorted({i for f in fixes for i in f["rows"]})
    LIVE.event("info", f"Re-running experiments {ids} against the FIXED system ...")
    after_dir, new_results = Engine(cfg, graph).run(plan, only=ids)
    after = build_fmea(new_results, base)
    cmp = compare_fmea(before, after)
    save_json(os.path.join(after_dir, "heal.json"), {"before_run": before_dir, "fixes": fixes, "compare": cmp})
    LIVE.set(fmea=after, fmea_compare=cmp, phase="healed")
    print("\nBEFORE -> AFTER")
    for c in cmp:
        print(f"  {c['id']} {c['failure_mode'][:34]:34} RPN {c['rpn_before']:>4} -> {c['rpn_after']:>4}  (-{c['reduction_pct']}%)")


def cmd_mystery(a, cfg):
    """A hidden fault the agents must diagnose from evidence alone. Same kill switch and sandbox rules as every experiment."""
    from agentic import runtime
    from core import mystery
    graph = need(DEPS_FILE, "map")
    runtime.RT["cfg"] = cfg
    if a.wait:
        mystery.wait_loop(cfg, graph, offline=a.offline)
        return
    if a.trials and a.trials > 1:
        lines = mystery.run_trials(a.trials, cfg, graph, offline=a.offline)
    else:
        lines = [mystery.run_trial(a.choice or "random", cfg, graph, offline=a.offline, chosen_by="terminal" if a.choice else "random")]
    print("\n" + mystery.format_table(lines))
    print(f"\nAll trials so far: {mystery.TRIALS_FILE}")


def cmd_replay(a, cfg):
    """Never again: replay saved failure scenarios against the current system. Exit code 1 if any fails (CI uses this)."""
    import glob
    from core import regression
    paths = [a.scenario] if a.scenario else sorted(glob.glob(os.path.join(ROOT, "scenarios", "*.json")))
    if not paths:
        sys.exit("No scenarios found in scenarios/. They are created when a confirmed failure is exported.")
    failed = 0
    for path in paths:
        r = regression.replay(path, cfg)
        failed += 0 if r.get("passed") else 1
        print(f"{'PASS' if r.get('passed') else 'FAIL'}  {r.get('scenario_id') or os.path.basename(path)}  {'; '.join(map(str, r.get('details') or []))[:160]}")
    sys.exit(1 if failed else 0)


def cmd_dashboard(a, cfg):
    subprocess.run([sys.executable, os.path.join(ROOT, "dashboard", "server.py")])


def cmd_panic(a, cfg):
    from core.faults import panic
    panic(cfg)


def cmd_demo(a, cfg):
    for fn in (cmd_map, cmd_baseline, cmd_plan, cmd_run, cmd_report):
        fn(a, cfg)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["up", "map", "baseline", "plan", "run", "agent", "autopilot", "graph", "report", "heal", "mystery", "replay", "dashboard", "panic", "demo"])
    p.add_argument("--offline", action="store_true", help="use cached AI answers (no internet needed)")
    p.add_argument("--only", help="comma list of experiment ids, e.g. E1,E3")
    p.add_argument("--compare", help="earlier run folder for before/after comparison")
    p.add_argument("--run-dir", help="report on a specific run folder")
    p.add_argument("--seconds", type=int, default=30, help="baseline duration")
    p.add_argument("--max", type=int, help="autopilot: maximum number of experiments (use 3 for a short demo)")
    p.add_argument("--goal", help="autopilot: a what-if question for the agents to investigate")
    p.add_argument("--approve", action="store_true", help="autopilot: ask a human before high-risk experiments")
    p.add_argument("--no-heal", action="store_true", help="autopilot: report only, do not apply fixes")
    p.add_argument("--wait", action="store_true", help="mystery: judge mode, wait for a pick on the dashboard")
    p.add_argument("--trials", type=int, help="mystery: run N random hidden-fault trials and print an accuracy table")
    p.add_argument("--choice", help="mystery: a menu id such as M-kill-redis (default: random)")
    p.add_argument("--scenario", help="replay: one scenario file (default: all in scenarios/)")
    p.add_argument("--fix", nargs="*", help="fix files from sandbox/fixes/ to apply on `up`")
    a = p.parse_args()
    globals()["cmd_" + a.command](a, load_config())


if __name__ == "__main__":
    main()
