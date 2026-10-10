#!/usr/bin/env python3
"""ChaosPilot CLI - the single entry point.

  python chaospilot.py up                 start the sandbox app (docker compose)
  python chaospilot.py map                auto-discover dependencies -> dependencies.json
  python chaospilot.py baseline           30s of steady traffic -> baseline.json
  python chaospilot.py plan               AI ranks experiments -> plan.json   (--offline = replay cache)
  python chaospilot.py run                run the plan with kill switch       (--only E1,E2)
  python chaospilot.py agent              AUTONOMOUS agent: AI picks each next attack after seeing results
  python chaospilot.py report             score + AI post-mortem              (--compare <old run dir>)
  python chaospilot.py dashboard          live dashboard on http://localhost:8000
  python chaospilot.py heal               FMEA -> pick fixes -> apply -> re-run -> prove RPN dropped
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


def cmd_report(a, cfg):
    try:
        from core.report import build_report
    except ImportError:
        sys.exit("core/report.py is not ready yet (Dipen's module)")
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
    p.add_argument("command", choices=["up", "map", "baseline", "plan", "run", "agent", "report", "heal", "dashboard", "panic", "demo"])
    p.add_argument("--offline", action="store_true", help="use cached AI answers (no internet needed)")
    p.add_argument("--only", help="comma list of experiment ids, e.g. E1,E3")
    p.add_argument("--compare", help="earlier run folder for before/after comparison")
    p.add_argument("--run-dir", help="report on a specific run folder")
    p.add_argument("--seconds", type=int, default=30, help="baseline duration")
    p.add_argument("--fix", nargs="*", help="fix files from sandbox/fixes/ to apply on `up`")
    a = p.parse_args()
    globals()["cmd_" + a.command](a, load_config())


if __name__ == "__main__":
    main()
