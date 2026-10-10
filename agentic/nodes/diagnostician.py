"""Phase 1 detection only. Root-cause analysis is deferred to Phase 2.
Existing investigation fields are preserved. LLM detection has a deterministic fallback.
"""
from core.common import LIVE
from core.knowledge import load_observation
from core.llm import ask_json
import json
import uuid


def detect_fault(res, configuration=None, baseline=None, observation=None):
    evidence, affected = [], set()
    configuration, baseline = configuration or {}, baseline or {}
    entries = {p['name']: p.get('entry') for p in configuration.get('probes', [])}
    for service in res.get('stuck_services') or []:
        affected.add(service)
        detail = (res.get('stuck_details') or {}).get(service) or {}
        evidence.append(f"{service} was stopped at inspection; exit_code={detail.get('exit_code', 'unknown')}")
    for probe, measured in (res.get('probes') or {}).items():
        rate = measured.get('error_rate')
        if isinstance(rate, (int, float)) and rate > 0:
            evidence.append(f"{probe}: error_rate={rate:.1%}")
            if entries.get(probe):
                affected.add(entries[probe])
        before = ((baseline.get('probes') or {}).get(probe) or {}).get('p95_ms')
        latency = measured.get('p95_ms')
        if isinstance(before, (int, float)) and before > 0 and isinstance(latency, (int, float)) and latency > 2 * before:
            evidence.append(f"{probe}: p95={latency}ms exceeds twice baseline={before}ms")
            if entries.get(probe):
                affected.add(entries[probe])
    lost = (res.get('delivery') or {}).get('lost')
    if isinstance(lost, (int, float)) and lost > 0:
        evidence.append(f"{lost} accepted votes undelivered at measurement cutoff")
    if 'recovery_s' in res and res['recovery_s'] is None:
        evidence.append('Recovery not observed within measurement window')
    if observation and observation.get('experiment') == res.get('id'):
        for event in observation.get('events') or []:
            if event.get('event') == 'die':
                evidence.append(f"Observer: {event.get('service')} exited at t={event.get('t')}; exit_code={event.get('exit_code')}")
                if event.get('service'):
                    affected.add(event['service'])
    if res.get('status') == 'aborted':
        evidence.append(f"Experiment stopped: {res.get('abort_reason') or 'reason unavailable'}")
    detected = bool(evidence)
    if not detected:
        evidence.append('No fault confirmed by available measurements; full health is not established')
    return ({'root_cause': 'Phase 2', 'evidence': evidence,
             'affected_services': sorted(affected), 'confidence': 'low',
             'suggested_fix': ''}, detected)


def investigate(cfg, graph, res, offline=False, baseline=None):
    """Ask the model to assess observed symptoms, never explain their cause."""
    final, detected = detect_fault(res, cfg, baseline, load_observation(res.get('id')))
    answer, source = ask_json(
        'fault_detection_' + uuid.uuid4().hex,
        'Assess fault evidence only. Never explain root causes or recommend fixes. '
        'Return JSON with fault_detected (boolean), evidence (exact strings copied from supplied evidence), '
        'and affected_services (a subset of supplied affected_services). '
        'A lack of evidence does not establish full health.',
        json.dumps({'measurements': {'probes': res.get('probes'), 'delivery': res.get('delivery'),
                                   'stuck_services': res.get('stuck_services')},
                    'evidence': final['evidence'], 'affected_services': final['affected_services']}),
        offline=offline, max_tokens=1000)
    valid = (isinstance(answer, dict) and type(answer.get('fault_detected')) is bool
             and answer['fault_detected'] == detected
             and isinstance(answer.get('evidence'), list) and bool(answer['evidence'])
             and all(isinstance(e, str) and e in final['evidence'] for e in answer['evidence'])
             and isinstance(answer.get('affected_services'), list)
             and all(isinstance(s, str) and s in final['affected_services'] for s in answer['affected_services']))
    if valid and source not in ('none', 'cache'):
        final = dict(final, evidence=answer['evidence'], affected_services=answer['affected_services'])
    else:
        source = 'rules'
    return {'final': final, 'tool_calls': 0, 'trace': [], 'source': source, 'fault_detected': detected}


def rule_based(res, graph=None):
    return detect_fault(res, observation=load_observation(res.get('id')))[0]


def diagnostician_node(state):
    LIVE.set(agent_active='diagnostician')
    inv = dict(state.get('investigations') or {})
    if not state.get('results'):
        return {'investigations': inv}
    from ..runtime import cfg
    res = state['results'][-1]
    final, detected = detect_fault(res, cfg(), state.get('baseline'), load_observation(res.get('id')))
    try:
        output = investigate(cfg(), state.get('graph') or {}, res, state.get('offline', False), state.get('baseline'))
        if output.get('final'):
            final = output['final']
        final['by'] = 'agent' if output.get('source') not in (None, 'rules', 'none', 'cache') else 'rules'
    except Exception:
        final['by'] = 'rules'
    status = 'Fault detected' if detected else 'No fault confirmed'
    LIVE.event('ai', f"[Diagnostician] {res['id']} {status}: {'; '.join(final['evidence'])}. Root-cause analysis: Phase 2")
    inv[res['id']] = final
    return {'investigations': inv}
