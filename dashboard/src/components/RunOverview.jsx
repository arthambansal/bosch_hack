import React from 'react';
import { arr, obj, num, running } from '../data.js';
import { Icon } from './ui.jsx';

export default function RunOverview({ state, connected, loading }) {
  const services = Object.keys(obj(obj(state.graph).services));
  const probes = Object.values(obj(state.probes)).filter(probe => num(obj(probe).n) && probe.n > 0);
  const hasQueue = Array.isArray(state.queue);
  const guard = obj(state.guard);
  const phase = typeof state.phase === 'string' ? state.phase : 'unknown';
  const phaseName = ({ stopping: 'Stopping', stopped: 'Stopped', completed: 'Run complete' })[state.run_status] || ({ stopped: 'Stopped', ran: 'Run complete', idle: 'Idle', running: 'Running', baseline: 'Capturing baseline', healing: 'Applying fixes', healed: 'Fixes applied', reporting: 'Reporting' })[phase] || `Phase: ${phase}`;
  const guardText = guard.tripped === true ? 'Tripped' : guard.tripped === false ? 'Not tripped' : 'Not available';
  const runName = state.run_dir ? String(state.run_dir).split(/[\\/]/).pop() : 'No run identified';
  return <section id="overview" className="run-overview" aria-labelledby="page-title">
    <div className="page-heading"><div><span className="eyebrow">OBSERVE. EXPERIMENT. UNDERSTAND.</span><h1 id="page-title">Run overview</h1><p>Your agents, experiments, and evidence. One complete picture.</p></div><div className="run-stamp"><span className={`phase-badge ${running(phase) && connected ? 'in-progress' : ''}`}><Icon name={phase === 'ran' ? 'check' : 'clock'} size={14} />{loading ? 'Loading state' : phaseName}</span><code title={state.run_dir || undefined}>{runName}</code></div></div>
    <div className="run-summary">
      <div className="summary-item"><span>Experiment records</span><strong>{hasQueue ? String(state.queue.length).padStart(2, '0') : 'Not available'}</strong><small>{hasQueue ? `${arr(state.queue).filter(item => obj(item).status === 'completed').length} completed · ${arr(state.queue).filter(item => obj(item).status === 'aborted').length} aborted` : 'No experiment queue supplied'}</small></div>
      <div className="summary-item"><span>Mapped services</span><strong>{services.length ? String(services.length).padStart(2, '0') : 'Not available'}</strong><small>{services.length ? `${arr(obj(state.graph).edges).length} dependency edges` : 'Awaiting application topology'}</small></div>
      <div className="summary-item"><span>Probes with samples</span><strong>{probes.length ? String(probes.length).padStart(2, '0') : 'Not available'}</strong><small>{probes.length ? connected && running(phase) ? 'Recent backend telemetry' : 'Last reported telemetry' : 'No measurements supplied'}</small></div>
      <div className="summary-item guard-summary"><span>Safety guard</span><strong className={guard.tripped === true ? 'critical-text' : 'text-value'}>{guardText}</strong><small>{guard.tripped === false ? connected && running(phase) ? 'Backend guard is reporting' : 'Last reported guard state' : guard.tripped === true ? 'See reported breach reasons' : 'Guard telemetry unavailable'}</small></div>
    </div>
  </section>;
}
