import React from 'react';
import { obj, arr, num, fmt, pct, running } from '../data.js';
import { EmptyState, SectionHeading } from './ui.jsx';

function ProbeReadout({ name, probe, baseline, current }) {
  const has = num(probe.n) && probe.n > 0;
  const samples = arr(probe.series).filter(r => Array.isArray(r) && num(r[0]) && num(r[1]) && typeof r[2] === 'boolean');
  const max = Math.max(1, ...samples.map(r => r[1]), num(baseline.p95_ms) ? baseline.p95_ms : 0);
  const earliest = Math.min(-1, ...samples.map(r => r[0]));
  const x = sample => 8 + (sample[0] - earliest) / (-earliest) * 484;
  const y = value => 70 - value / max * 62;
  return <article className="probe-readout"><div className="probe-heading"><h3>{name}</h3><span>{has ? current ? 'Recent window' : 'Last reported' : 'No samples'}</span></div>
    <div className="probe-values"><div><small>p95 latency</small><strong>{has ? fmt(probe.p95_ms) : 'Not available'}{has && num(probe.p95_ms) && <span>ms</span>}</strong><small>Baseline {fmt(baseline.p95_ms, ' ms')}</small></div><div><small>Error rate</small><strong>{has ? pct(probe.error_rate) : 'Not available'}</strong><small>Baseline {pct(baseline.error_rate)}</small></div><div><small>Requests</small><strong>{fmt(probe.n)}</strong><small>Baseline {fmt(baseline.n)}</small></div></div>
    {samples.length ? <div className="probe-chart"><svg viewBox="0 0 500 82" role="img" aria-label={`${name}: observed latency over ${fmt(-earliest)} seconds; maximum scale ${fmt(max)} ms. ${samples.filter(r => !r[2]).length} failed requests.`}>
      {num(baseline.p95_ms) && <line x1="8" x2="492" y1={y(baseline.p95_ms)} y2={y(baseline.p95_ms)} className="baseline-line" />}
      <polyline points={samples.map(r => `${x(r)},${y(r[1])}`).join(' ')} className="latency-line" />{samples.filter(r => !r[2]).map((r, i) => <circle key={i} cx={x(r)} cy={y(r[1])} r="3" className="failed-sample" />)}
    </svg><div className="chart-caption"><span>{fmt(earliest, ' s')} → 0 s</span><span>Latency · red marks failures{num(baseline.p95_ms) ? ' · dashed baseline p95' : ''}</span></div></div> : <p className="no-series">No latency history supplied.</p>}
  </article>;
}

export default function TelemetryPanel({ state, connected, id = 'telemetry' }) {
  const probes = obj(state.probes), baseline = obj(obj(state.baseline).probes), limits = obj(state.thresholds);
  const names = [...new Set([...Object.keys(probes), ...Object.keys(baseline)])];
  return <section className="surface telemetry-panel" id={id} aria-labelledby={`${id}-title`}>
    <SectionHeading id={`${id}-title`} eyebrow="MEASUREMENTS" title="Signals, without the guesswork" description="Observed performance against the healthy baseline." />
    {names.length ? <div className="probe-list">{names.map(name => <ProbeReadout key={name} name={name} probe={obj(probes[name])} baseline={obj(baseline[name])} current={connected && running(state.phase)} />)}</div> : <EmptyState icon="telemetry" title="Waiting for the first measurement">No probe samples or baseline have been supplied. Latency, errors, and request counts will appear here as they arrive.</EmptyState>}
    <div className="telemetry-limits"><span><small>Error ceiling</small><strong>{pct(limits.max_error_rate)}</strong></span><span><small>p95 ceiling</small><strong>{fmt(limits.max_p95_ms, ' ms')}</strong></span><small>Backend safety thresholds</small></div>
  </section>;
}
