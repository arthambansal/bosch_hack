"""Confirmed failures replayed through the production engine. Owner: Tejas."""
import hashlib
import json
import math
import re
import time
from pathlib import Path
from .common import LIVE, ROOT, RUNS_DIR, STOP_FILE, probes_affected

SCENARIOS = Path(ROOT) / 'scenarios'


def _warn(operation, exc):
    try:
        LIVE.event('warn', f'[Regression] {operation} not available: {exc}')
    except Exception:
        pass  # Disk failure must not cause a second failure while logging.


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def export_scenario(result, investigation, run_dir):
    """Export measured failures only; exclusive creation preserves first evidence."""
    try:
        if result.get('status') not in ('completed', 'aborted'):
            return None
        if 'injection failed' in (result.get('abort_reason') or '').lower():
            return None
        lost = (result.get('delivery') or {}).get('lost')
        stuck = result.get('stuck_services')
        unrecovered = 'recovery_s' in result and result['recovery_s'] is None
        if not (stuck or (_number(lost) and lost > 0) or unrecovered):
            return None
        if not _number(result.get('fault_window_s')):
            raise ValueError('measured fault window required before exporting')
        steps = result.get('steps')
        if not isinstance(steps, list) or not steps:
            raise ValueError('confirmed result has no replayable steps')
        evidence = list(dict.fromkeys(x for x in investigation.get('evidence', [])
                                     if isinstance(x, str) and x.strip()))[:4]
        if len(evidence) < 2:
            raise ValueError('need at least two investigation evidence lines')
        invariants = []
        if _number(lost) and lost > 0:
            invariants.append('no_vote_loss')
        if stuck or unrecovered:
            invariants.append('no_stuck_services')
        recovery = result.get('recovery_s')
        if _number(recovery):
            invariants.append(f'recovers_within_s:{recovery:g}')
        digest = hashlib.sha256(json.dumps(steps, sort_keys=True).encode()).hexdigest()[:12]
        slug = re.sub(r'[^a-z0-9]+', '-', str(result.get('name') or result.get('id') or 'failure').lower()).strip('-')[:65]
        scenario_id = f'{slug or "failure"}-{digest}'
        body = {'id': scenario_id, 'name': result.get('name') or scenario_id, 'steps': steps,
                'invariants': invariants, 'from_run': str(run_dir), 'evidence': evidence}
        SCENARIOS.mkdir(parents=True, exist_ok=True)
        path = SCENARIOS / f'{scenario_id}.json'
        encoded = json.dumps(body, indent=2, allow_nan=False) + '\n'
        try:
            with path.open('x', encoding='utf-8') as handle:
                handle.write(encoded)
        except FileExistsError:
            return None
        return str(path)
    except Exception as exc:
        _warn('export', exc)
        return None


def replay(path, cfg):
    """No AI. Fail closed on absent measurements, unsafe steps, STOP or denied approval."""
    outcome = {'scenario_id': None, 'passed': False, 'details': []}
    eng = None
    scenario_id = None
    run_folder = None
    try:
        source = Path(path).resolve()
        if source.parent != SCENARIOS.resolve() or source.name.startswith('.'):
            raise ValueError('scenario must be a direct scenarios/*.json file')
        scenario = json.loads(source.read_text(encoding='utf-8'))
        scenario_id = scenario['id']
        if not isinstance(scenario_id, str) or source.stem != scenario_id:
            scenario_id = None
            raise ValueError('scenario id must match its filename')
        outcome['scenario_id'] = scenario_id
        steps, invariants = scenario['steps'], scenario['invariants']
        if not isinstance(steps, list) or not 1 <= len(steps) <= 2:
            raise ValueError('Governor permits one or two faults')
        if not isinstance(invariants, list) or not invariants:
            raise ValueError('scenario has no invariants')
        limits = {}
        for inv in invariants:
            if inv in ('no_vote_loss', 'no_stuck_services'):
                continue
            if not isinstance(inv, str) or not inv.startswith('recovers_within_s:'):
                raise ValueError(f'unknown invariant {inv}')
            limit = float(inv.split(':', 1)[1])
            if not _number(limit):
                raise ValueError('invalid recovery limit')
            limits[inv] = limit
        services = cfg['services']
        down = set()
        for step in steps:
            if step['target'] not in services or step['type'] not in {'kill', 'pause', 'partition', 'latency', 'spike'}:
                raise ValueError('unknown sandbox target or fault')
            delay = step.get('delay_s', 0)
            if not _number(delay) or delay >= cfg['safety']['max_experiment_s']:
                raise ValueError('delay exceeds experiment safety window')
            if services[step['target']].get('stateful') and step['type'] in {'kill', 'pause', 'partition'}:
                down.add(step['target'])
        if len(down) > 1:
            raise ValueError('Governor permits at most one data store down')
        if Path(STOP_FILE).exists():
            raise ValueError('STOP is present')
        # Match the Governor limits without replacing its process-global configuration.
        # Also honour the blueprint human gate for data-store disruption.
        if len(steps) > 1 or down:
            from agentic.gate import ask_human
            answer = ask_human({'id': scenario_id, 'name': scenario['name'], 'steps': steps,
                                'question': f'Approve regression {scenario_id}?', 'reason': 'Replay confirmed failure'})
            if str(answer).lower() not in ('yes', 'y', 'true', 'approved', 'approve'):
                raise ValueError('human approval denied or unavailable')
        if Path(STOP_FILE).exists():
            raise ValueError('STOP is present')
        graph = {'services': {n: {**s, 'depends_on': []} for n, s in services.items()}}
        for a, b in cfg.get('manual_edges', []):
            graph['services'][a]['depends_on'].append(b)
        exp = {'id': scenario_id, 'name': scenario['name'], 'steps': steps,
               'reason': 'Replay confirmed failure', 'hypothesis': None,
               'predicted_probes': probes_affected(cfg, graph, [s['target'] for s in steps])}
        from .engine import Engine
        run_folder = Path(RUNS_DIR) / f"replay_{time.time_ns()}"
        run_folder.mkdir(parents=True)
        (run_folder / "scenario.json").write_text(json.dumps(scenario, indent=2), encoding="utf-8")
        eng = Engine(cfg, graph)
        eng.prober.start()
        result = eng.run_experiment(exp)
        (run_folder / "results.json").write_text(json.dumps([result], indent=2), encoding="utf-8")
        abort = (result.get('abort_reason') or '').lower()
        valid = (result.get('status') in ('completed', 'aborted')
                 and not any(x in abort for x in ('injection failed', 'manual kill switch', 'hard time limit'))
                 and not Path(STOP_FILE).exists())
        checks = [valid, _number(result.get('recovery_s'))]
        outcome['details'].append(f'experiment ran: {valid}; probe recovery measured: {checks[1]}')
        for inv in invariants:
            if inv == 'no_vote_loss':
                value = (result.get('delivery') or {}).get('lost')
                ok = _number(value) and value == 0
            elif inv == 'no_stuck_services':
                value = result.get('stuck_services')
                ok = isinstance(value, list) and not value
            else:
                value = result.get('recovery_s')
                ok = _number(value) and value <= limits[inv]
            checks.append(ok)
            outcome['details'].append(f'{inv}: {"pass" if ok else "fail"} (measured {value!r})')
        outcome['passed'] = all(checks)
    except Exception as exc:
        _warn('replay', exc)
        outcome['details'].append(str(exc))
    finally:
        if eng is not None:
            for cleanup in (eng._restore_all, eng.prober.stop):
                try:
                    cleanup()
                except Exception as exc:
                    _warn('cleanup', exc)
                    outcome['passed'] = False
                    outcome['details'].append('cleanup not available')
        if run_folder is not None:
            try:
                (run_folder / "replay.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
            except Exception as exc:
                _warn("replay evidence", exc)
                outcome["passed"] = False
                outcome["details"].append("replay evidence not available")
        if scenario_id is not None:
            try:
                status_file = SCENARIOS / '.status.json'
                statuses = json.loads(status_file.read_text(encoding='utf-8')) if status_file.exists() else {}
                statuses[scenario_id] = {'last_status': 'pass' if outcome['passed'] else 'fail', 'last_run_at': time.time()}
                tmp = SCENARIOS / '.status.json.tmp'
                tmp.write_text(json.dumps(statuses, indent=2), encoding='utf-8')
                tmp.replace(status_file)
            except Exception as exc:
                _warn('status write', exc)
                outcome['passed'] = False
                outcome['details'].append('status recording not available')
    return outcome


def list_scenarios():
    """One live-state row per invariant; unknown status stays never_run."""
    try:
        status_file = SCENARIOS / '.status.json'
        statuses = json.loads(status_file.read_text(encoding='utf-8')) if status_file.exists() else {}
        rows = []
        for path in sorted(SCENARIOS.glob('*.json')):
            if path.name.startswith('.'):
                continue
            data = json.loads(path.read_text(encoding='utf-8'))
            status = statuses.get(data['id'], {})
            for invariant in data['invariants']:
                rows.append({'scenario_id': data['id'], 'file': f'scenarios/{path.name}', 'invariant': invariant,
                             'last_status': status.get('last_status', 'never_run'), 'last_run_at': status.get('last_run_at')})
        return rows
    except Exception as exc:
        _warn('listing', exc)
        return []
