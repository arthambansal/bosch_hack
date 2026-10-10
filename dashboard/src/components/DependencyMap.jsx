import React, { useState } from 'react';
import { obj, arr, num, running } from '../data.js';
import { EmptyState, SectionHeading, Icon } from './ui.jsx';

export default function DependencyMap({ state, connected }) {
  const services = obj(obj(state.graph).services), edges = arr(obj(state.graph).edges);
  const names = Object.keys(services), faults = arr(state.faulted), probes = obj(state.probes);
  const [selected, setSelected] = useState(null);
  const width = names.length > 6 ? 700 : 500, height = names.length > 6 ? 400 : 290;
  const positions = Object.fromEntries(names.map((name, i) => {
    const angle = -Math.PI / 2 + 2 * Math.PI * i / names.length;
    return [name, { x: width / 2 + (names.length === 1 ? 0 : width / 2 - 80) * Math.cos(angle), y: height / 2 + (names.length === 1 ? 0 : height / 2 - 42) * Math.sin(angle) }];
  }));
  function health(name) {
    const injected = faults.filter(f => obj(f).target === name);
    const probe = obj(probes[name === 'vote' ? 'vote_write' : name === 'result' ? 'result_page' : '']);
    const current = connected && running(state.phase);
    if (injected.length) return { tone: 'fault', label: `${current ? 'Injected' : 'Last injected'}: ${injected.map(f => f.type).join(', ')}` };
    if (current && num(probe.n) && probe.n > 0 && num(probe.error_rate)) return { tone: probe.error_rate === 0 ? 'healthy' : 'warning', label: probe.error_rate === 0 ? 'Entry probe passing' : 'Entry probe errors' };
    return { tone: 'unknown', label: 'Health unknown' };
  }
  // Clip straight connectors at the service boxes. Relationships come only from edges.
  function connector(from, to) {
    const a = positions[from], b = positions[to];
    if (!a || !b) return null;
    if (from === to) return `M${a.x + 25} ${a.y - 28}v-14h-50v14`;
    const dx = b.x - a.x, dy = b.y - a.y;
    const fraction = Math.min(Math.abs(dx) > 0 ? 60 / Math.abs(dx) : Infinity, Math.abs(dy) > 0 ? 28 / Math.abs(dy) : Infinity);
    return `M${a.x + dx * fraction} ${a.y + dy * fraction}L${b.x - dx * fraction} ${b.y - dy * fraction}`;
  }
  return <section className="surface topology-panel" id="topology" aria-labelledby="topology-title">
    <SectionHeading id="topology-title" eyebrow="APPLICATION" title="Know your dependencies" description="The relationships behind the blast radius."><span className="section-count">{names.length ? `${names.length} services` : 'No map'}</span></SectionHeading>
    {names.length ? <>
      <div className="topology-scroll" tabIndex="0" role="region" aria-label="Service dependency map">
        <svg className="topology-svg" viewBox={`0 0 ${width} ${height}`} style={{ minWidth: names.length > 6 ? 600 : 360 }}>
          <defs><marker id="service-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M1 1L9 5L1 9" fill="none" stroke="currentColor" strokeWidth="1.5" /></marker></defs>
          {edges.map((raw, i) => { const edge = obj(raw), d = connector(edge.from, edge.to); return d ? <path key={i} d={d} className={`service-connection ${selected && [edge.from, edge.to].includes(selected) ? 'focused' : ''}`} markerEnd="url(#service-arrow)"><title>{`${edge.from} → ${edge.to}: ${arr(edge.evidence).join('; ')}`}</title></path> : null; })}
          {names.map(name => { const point = positions[name], status = health(name); return <foreignObject key={name} x={point.x - 60} y={point.y - 28} width="120" height="56"><button className={`service-node ${status.tone} ${selected === name ? 'selected' : ''}`} aria-pressed={selected === name} aria-label={`${name}, ${status.label}`} onClick={() => setSelected(selected === name ? null : name)}><strong><i />{name}</strong><small>{String(obj(services[name]).role || 'Role unspecified')}</small></button></foreignObject>; })}
        </svg>
      </div>
      {selected && services[selected] && <div className="service-inspector"><strong>{selected}</strong><span>{health(selected).label}</span><small>{obj(services[selected]).stateful === true ? 'Stateful service' : 'Statefulness not asserted'}</small></div>}
      <details className="edge-details"><summary>{edges.length} directional relationships <Icon name="chevron" size={14} /></summary><ul>{edges.map((raw, i) => { const edge = obj(raw); return <li key={i}><span>{edge.from} <span aria-hidden="true">→</span> {edge.to}</span><small>{arr(edge.evidence).join(' · ') || 'No supporting evidence supplied'}</small></li>; })}</ul>{!edges.length && <p>No dependency edges supplied.</p>}</details>
    </> : <EmptyState icon="topology" title="Your system map belongs here">No application topology has been published in this snapshot. Services and directional connections will appear when available.</EmptyState>}
    <div className="panel-foot"><span><i className="status-dot unknown" />Unknown is not healthy</span><small>Entry probes verify paths, not every container.</small></div>
  </section>;
}
