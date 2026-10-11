import React, { useId, useState } from 'react';
import { running } from '../data.js';
import { WORKFLOW_NODES, WORKFLOW_ROUTES, nodeLabel, activeNodeId } from '../workflow.js';
import { Icon } from './ui.jsx';

export default function AgentWorkflow({ state, connected }) {
  const markerId = `workflow-arrow-${useId().replace(/:/g, '')}`;
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState('map');
  const candidate = activeNodeId(state.agent_active);
  const active = connected && !['stopped', 'completed'].includes(state.run_status) && running(state.phase) && WORKFLOW_NODES.some(node => node.id === candidate) ? candidate : null;
  const status = !connected ? 'Live status unavailable' : state.run_status === 'stopping' ? 'Stopping' : state.run_status === 'stopped' ? 'Run stopped' : state.phase === 'ran' ? 'Run complete' : state.phase === 'idle' ? 'Idle' : active ? state.agent_active === 'human' ? 'Awaiting approval' : `${nodeLabel(active)} active` : 'Active step unknown';
  const selectedNode = WORKFLOW_NODES.find(node => node.id === selected);
  const outgoing = WORKFLOW_ROUTES.filter(route => route.from === selected);
  const drawn = selected ? outgoing : WORKFLOW_ROUTES.filter(route => route.overview);

  return <section className="workflow-panel" id="workflow" aria-labelledby="workflow-title">
    <div className="workflow-heading">
      <div><span className="eyebrow">THE DECISION ENGINE</span><h2 id="workflow-title">Agent workflow</h2><p>Four reasoning agents. Deterministic safety at every experiment.</p></div>
      <div className="workflow-tools"><span className={`workflow-status ${active ? 'has-active' : ''}`}><i />{status}</span><div className="segmented dark" aria-label="Workflow view"><button aria-pressed={view === 'map'} onClick={() => setView('map')}>Map</button><button aria-pressed={view === 'routes'} onClick={() => setView('routes')}>All 18 routes</button></div></div>
    </div>
    {view === 'map' ? <>
      <div className="workflow-caption"><span>{selectedNode ? <>Inspecting <strong>{selectedNode.label}</strong> · {outgoing.length} outgoing {outgoing.length === 1 ? 'route' : 'routes'}</> : 'Overview · select a step to inspect every outgoing route'}</span>{selected && <button className="text-button light" onClick={() => setSelected(null)}>Reset view <span aria-hidden="true">↗</span></button>}</div>
      <div className="workflow-scroll" tabIndex="0" role="region" aria-label="Interactive agent map, scroll horizontally on smaller screens">
        <svg className="workflow-svg" viewBox="0 0 1080 420" aria-label="Agent routing map">
          <defs><marker id={markerId} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto" overflow="visible"><path d="M1 1L9 5L1 9" fill="none" stroke={selected ? 'var(--teal-ink, #075e63)' : 'var(--graph-edge, #58758b)'} strokeWidth="1.5" /></marker></defs>
          <text x="24" y="31" className="map-lane">01 — DISCOVER & EXPERIMENT</text>
          <text x="24" y="250" className="map-lane">02 — LEARN & VERIFY</text>
          <line x1="24" x2="1056" y1="209" y2="209" className="lane-divider" />
          {drawn.map(route => <path key={`${route.from}-${route.to}`} d={route.path} data-from={route.from} data-to={route.to} className={`workflow-edge ${selected ? 'focused' : ''}`} markerEnd={`url(#${markerId})`}><title>{`${nodeLabel(route.from)} → ${nodeLabel(route.to)}: ${route.when}`}</title></path>)}
          {!selected && <><text x="105" y="63" className="terminal-label">START</text><text x="760" y="402" className="terminal-label">END</text><text x="288" y="232" className="connector-note">No proposal</text><text x="997" y="232" className="connector-note" textAnchor="middle">Anomaly</text></>}
          {WORKFLOW_NODES.map(node => <foreignObject x={node.x - 3} y={node.y - 3} width="148" height="86" key={node.id}>
            <button className={`agent-node ${node.type} ${selected === node.id ? 'is-selected' : ''} ${active === node.id ? 'is-active' : ''}`} onClick={() => setSelected(selected === node.id ? null : node.id)} aria-pressed={selected === node.id} aria-label={`Inspect ${node.label} routes${active === node.id ? ', currently active' : ''}`}>
              <span className="agent-type"><span className="agent-code">{node.code}</span>{node.type === 'reasoning' ? 'REASONING' : 'SUPPORT'}</span>
              <strong>{node.label}</strong><span className="node-port" aria-hidden="true" />{active === node.id && <span className="active-tag">ACTIVE</span>}
            </button>
          </foreignObject>)}
        </svg>
      </div>
      <div className="workflow-legend"><span><i className="legend-reasoning" />Reasoning agent</span><span><i className="legend-support" />Supporting step</span><span><i className="legend-active" />Current backend step</span><span className="legend-note">Arrows describe routing, not completed execution.</span></div>
      <div className="route-inspector">
        <div className="inspector-title"><span className="inspector-symbol"><Icon name={selectedNode ? 'workflow' : 'search'} /></span><div><h3>{selectedNode ? selectedNode.label : 'Explore how the team makes decisions'}</h3><p>{selectedNode ? selectedNode.description : 'Select any node above to reveal its branches, retries, and stopping conditions.'}</p></div></div>
        {selectedNode ? <div className="decision-list">{outgoing.map(route => <div className="decision" key={route.to}><Icon name="arrow" size={16} /><div><strong>{nodeLabel(route.to)}</strong><small>{route.when}</small></div></div>)}</div> : <span className="architecture-note">10 steps<span>18 permitted transitions</span></span>}
      </div>
    </> : <div className="route-table-wrap" tabIndex="0" role="region" aria-label="All workflow routing relationships"><table className="route-table"><thead><tr><th>From</th><th>To</th><th>Condition</th></tr></thead><tbody>{WORKFLOW_ROUTES.map(route => <tr key={`${route.from}-${route.to}`}><td>{nodeLabel(route.from)}</td><td>{nodeLabel(route.to)}</td><td>{route.when}</td></tr>)}</tbody></table><p className="routing-footnote">Observer telemetry is collected within execution; Observer is not a separate node in the current graph.</p></div>}
  </section>;
}
