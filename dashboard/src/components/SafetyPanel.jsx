import React from 'react';
import { obj, arr, num, fmt, pct, running } from '../data.js';
import { Icon, SectionHeading } from './ui.jsx';
import { useControls } from './ControlProvider.jsx';
import ControlFeedback from './ControlFeedback.jsx';
import InfoTooltip from './InfoTooltip.jsx';

export function StopControl({ compact = false }) {
  const controls = useControls();
  const loading = controls?.stopResult.status === 'loading';
  return <button className={`stop-button ${compact ? 'compact' : ''}`} disabled={!controls?.stopAvailable} onClick={controls?.openStopDialog} aria-busy={loading} aria-describedby="stop-note"><Icon name="stop" size={16} /><span>{loading ? 'Requesting stop…' : 'Emergency stop'}{!compact && <small>{loading ? 'Waiting for acknowledgement' : controls?.stopAvailable ? 'Confirmation required' : 'Unavailable'}</small>}</span>{compact && !controls?.stopAvailable && <Icon name="lock" size={12} />}</button>;
}

export default function SafetyPanel({ state, connected, id = 'controls' }) {
  const guard = obj(state.guard), limits = obj(state.thresholds);
  const measurable = num(guard.ticks) && num(limits.breach_ticks) && limits.breach_ticks > 0;
  const ratio = measurable ? Math.min(1, Math.max(0, guard.ticks / limits.breach_ticks)) : null;
  const status = guard.tripped === true ? 'Guard tripped' : guard.tripped === false ? 'Not tripped' : 'Guard state unknown';
  const current = connected && running(state.phase);
  const controls = useControls();
  return <section className="control-panel" id={id} aria-labelledby={`${id}-title`}>
    <SectionHeading id={`${id}-title`} eyebrow="OPERATOR CONTROLS" title={<>Safety comes first <InfoTooltip term="guard ticks" /></>} description="Deterministic limits. Human oversight." />
    <div className={`guard-instrument ${guard.tripped === true ? 'tripped' : ''}`}><div className="guard-dial"><svg viewBox="0 0 80 80" aria-hidden="true"><circle cx="40" cy="40" r="33" className={`dial-track ${ratio === null ? 'unavailable' : ''}`} />{ratio !== null && <circle cx="40" cy="40" r="33" className="dial-value" strokeDasharray={`${ratio * 207.35} 207.35`} transform="rotate(-90 40 40)" />}</svg><span>{ratio === null ? 'Not available' : fmt(guard.ticks)}</span></div><div><strong>{status}</strong><p>{guard.tripped === undefined ? 'No guard telemetry supplied' : current ? 'Reported by the runtime guard' : 'Last reported guard state'}</p><small>{measurable ? `${fmt(guard.ticks)} / ${fmt(limits.breach_ticks)} consecutive breaches` : 'Breach counter unavailable'}</small></div></div>
    <dl className="safety-readouts"><div><dt>Error ceiling</dt><dd>{pct(limits.max_error_rate)}</dd></div><div><dt>p95 ceiling</dt><dd>{fmt(limits.max_p95_ms, ' ms')}</dd></div><div><dt>Elapsed fault time</dt><dd>{fmt(guard.elapsed, ' s')}</dd></div><div><dt>Hard time limit</dt><dd>{fmt(limits.max_experiment_s, ' s')}</dd></div></dl>
    {arr(guard.reasons).length > 0 && <ul className="guard-reasons">{guard.reasons.map((reason, index) => <li key={index}>{String(reason)}</li>)}</ul>}
    <div className="run-progress" role="status"><h3>Run progress</h3><strong>{({ running: 'Running', stopping: 'Stopping — awaiting cleanup', stopped: 'Stopped (reported by backend)', completed: 'Completed (reported by backend)' })[controls?.runStatus] || 'Run status unavailable'}</strong>
      <p>{obj(controls?.cleanup).done === true ? 'Backend marked cleanup done.' : 'Cleanup completion is unconfirmed.'}</p>
      {typeof controls?.reportPath === 'string' && controls.reportPath ? <><small>Report path reported by backend</small><code>{controls.reportPath}</code></> : <small>No report path reported yet.</small>}
    </div>
    <div className="emergency-area"><div><h3>Emergency stop</h3><p>Stop the run and request cleanup.</p></div><StopControl />
      <ControlFeedback result={controls?.stopResult} />
      <p className="stop-note">STOP requests cancellation and cleanup. Acceptance does not confirm cleanup completion; watch the backend run status above.</p>
      <button className="text-button stop-review" onClick={controls?.openStopDialog} disabled={!controls}>Review STOP confirmation <span aria-hidden="true">↗</span></button>
    </div>
  </section>;
}
