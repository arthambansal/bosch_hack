import React from 'react';
import { obj, arr, num, fmt, pct, running } from '../data.js';
import ApprovalPanel from './ApprovalPanel.jsx';
import { Icon, SectionHeading } from './ui.jsx';

export function StopControl({ compact = false }) {
  return <button className={`stop-button ${compact ? 'compact' : ''}`} disabled aria-describedby="stop-note"><Icon name="stop" size={16} /><span>Emergency stop{!compact && <small>Unavailable</small>}</span>{compact && <Icon name="lock" size={12} />}</button>;
}

export default function SafetyPanel({ state, connected }) {
  const guard = obj(state.guard), limits = obj(state.thresholds);
  const measurable = num(guard.ticks) && num(limits.breach_ticks) && limits.breach_ticks > 0;
  const ratio = measurable ? Math.min(1, Math.max(0, guard.ticks / limits.breach_ticks)) : null;
  const status = guard.tripped === true ? 'Guard tripped' : guard.tripped === false ? 'Not tripped' : 'Guard state unknown';
  const current = connected && running(state.phase);
  return <section className="control-panel" id="controls" aria-labelledby="controls-title">
    <SectionHeading id="controls-title" eyebrow="OPERATOR CONTROLS" title="Safety comes first" description="Deterministic limits. Human oversight." />
    <div className={`guard-instrument ${guard.tripped === true ? 'tripped' : ''}`}><div className="guard-dial"><svg viewBox="0 0 80 80" aria-hidden="true"><circle cx="40" cy="40" r="33" className={`dial-track ${ratio === null ? 'unavailable' : ''}`} />{ratio !== null && <circle cx="40" cy="40" r="33" className="dial-value" strokeDasharray={`${ratio * 207.35} 207.35`} transform="rotate(-90 40 40)" />}</svg><span>{ratio === null ? '—' : fmt(guard.ticks)}</span></div><div><strong>{status}</strong><p>{guard.tripped === undefined ? 'No guard telemetry supplied' : current ? 'Reported by the runtime guard' : 'Last reported guard state'}</p><small>{measurable ? `${fmt(guard.ticks)} / ${fmt(limits.breach_ticks)} consecutive breaches` : 'Breach counter unavailable'}</small></div></div>
    <dl className="safety-readouts"><div><dt>Error ceiling</dt><dd>{pct(limits.max_error_rate)}</dd></div><div><dt>p95 ceiling</dt><dd>{fmt(limits.max_p95_ms, ' ms')}</dd></div><div><dt>Elapsed fault time</dt><dd>{fmt(guard.elapsed, ' s')}</dd></div><div><dt>Hard time limit</dt><dd>{fmt(limits.max_experiment_s, ' s')}</dd></div></dl>
    {arr(guard.reasons).length > 0 && <ul className="guard-reasons">{guard.reasons.map((reason, index) => <li key={index}>{String(reason)}</li>)}</ul>}
    <ApprovalPanel request={state.approval_request} phase={state.phase} connected={connected} />
    <div className="emergency-area"><div><h3>Emergency stop</h3><p>Stop the run and request cleanup.</p></div><StopControl /><p id="stop-note">Unavailable: the STOP endpoint is not connected. Future requests require confirmation; an accepted request must not be treated as completed cleanup.</p></div>
  </section>;
}
