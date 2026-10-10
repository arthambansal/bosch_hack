import React, { useState } from 'react';
import { obj, arr, fmt, localTime } from '../data.js';
import { textValue, agentEvents } from '../viewModel.js';
import { WORKFLOW_NODES, WORKFLOW_ROUTES, nodeLabel } from '../workflow.js';
import { EmptyState, SectionHeading } from './ui.jsx';
import InfoTooltip from './InfoTooltip.jsx';

export function ViewHeading({ title, children }) {
  return <div className="view-heading"><span className="eyebrow">CHAOSPILOT / CONTROL ROOM</span><h1>{title}</h1><p>{children}</p></div>;
}

export function ExperimentDetails({ state }) {
  const experiment = obj(state.experiment), queue = arr(state.queue);
  return <section className="surface evidence-panel" aria-labelledby="experiment-details-title">
    <SectionHeading id="experiment-details-title" eyebrow="EXPERIMENT RECORD" title="What is being tested" description="Published experiment intent and reported queue outcomes." />
    <div className="panel-body"><dl className="detail-list"><div><dt>Experiment</dt><dd>{textValue(experiment.name)} <code>{textValue(experiment.id)}</code></dd></div><div><dt>Reason for selection</dt><dd>{textValue(experiment.reason)}</dd></div><div><dt>Hypothesis · not an observed result</dt><dd>{textValue(experiment.hypothesis)}</dd></div><div><dt>Predicted probes · not measurements</dt><dd>{arr(experiment.predicted_probes).length ? experiment.predicted_probes.join(', ') : 'Not available'}</dd></div></dl>
      <h3>Published fault steps</h3>{arr(experiment.steps).length ? <ol className="fault-steps">{experiment.steps.map((raw, index) => { const step = obj(raw); return <li key={index}><strong>{textValue(step.type)}</strong><span>{textValue(step.target)}</span><small>Delay: {fmt(step.delay_s, ' s')}</small></li>; })}</ol> : <p className="missing-data">Not available</p>}
      <h3>Experiment queue</h3>{queue.length ? <div className="data-table-scroll" tabIndex="0" role="region" aria-label="Experiment queue"><table className="evidence-table"><thead><tr><th>Experiment</th><th>Reported status</th><th>Selection reason</th></tr></thead><tbody>{queue.map((raw, index) => { const item = obj(raw); return <tr key={index}><td><code>{textValue(item.id)}</code><strong>{textValue(item.name)}</strong></td><td>{textValue(item.status)}</td><td>{textValue(item.reason)}</td></tr>; })}</tbody></table></div> : <p className="missing-data">Not available</p>}
    </div>
  </section>;
}

const INPUTS = {
  cartographer: 'Service topology, configuration, and available observations.',
  experimenter: 'Application model, hypotheses, previous experiment results, and safety feedback.',
  governor: 'Proposed fault steps and deterministic safety policy.',
  approval: 'The published gate token, experiment question, reason, and expiry.',
  execute: 'The approved experiment, configured probes, and safety limits.',
  evaluate: 'Observed experiment results and the baseline.',
  diagnostician: 'Anomalous results, probe measurements, logs, and observed symptoms.',
  remediator: 'Investigations, applicable fix catalog, and prior verification feedback.',
  verify: 'Pending fixes and the targeted experiments to re-run.',
  reporter: 'Experiment results, investigations, FMEA, and verification comparisons.',
};
const DECISIONS = {
  cartographer: 'Proposes testable failure hypotheses; does not inject faults.',
  experimenter: 'Selects an experiment or finishes planning when no proposal remains.',
  governor: 'Accepts or rejects the proposal using deterministic limits.',
  approval: 'Passes an approved proposal onward or returns a denial to planning.',
  execute: 'Applies authorized fault steps; the guard can abort execution.',
  evaluate: 'Computes risk in code and routes anomalous results to diagnosis.',
  diagnostician: 'Reports a cause with evidence; missing evidence must not become a confirmed finding.',
  remediator: 'Selects applicable fixes and requests verification; a proposal is not proof of recovery.',
  verify: 'Compares measured risk after re-running; routes according to improvement and attempt limits.',
  reporter: 'Publishes the report and deterministic resilience score.',
};
const EVENT_LABELS = { governor: 'Governor', approval: 'Human', execute: 'Executor', evaluate: 'Evaluator', verify: 'Verifier' };

export function AgentGuide({ state }) {
  const [selected, setSelected] = useState('cartographer');
  const node = WORKFLOW_NODES.find(item => item.id === selected);
  const events = agentEvents(state, EVENT_LABELS[node.id] || node.label);
  const routes = WORKFLOW_ROUTES.filter(route => route.from === node.id);
  let output = 'Not available';
  if (node.id === 'cartographer' && Object.keys(obj(obj(state.graph).services)).length) output = `${Object.keys(state.graph.services).length} published services. See the dependency map.`;
  if (node.id === 'approval' && ['approved', 'denied'].includes(obj(state.approval_result).answer)) output = `${state.approval_result.answer} · gate ${textValue(state.approval_result.gate_id)} · source ${textValue(state.approval_result.source)}`;
  if (node.id === 'execute' && arr(state.queue).length) output = state.queue.map(item => `${textValue(obj(item).id)}: ${textValue(obj(item).status)}`).join(' · ');
  if (node.id === 'evaluate' && arr(state.fmea).length) output = `${state.fmea.length} published FMEA rows. See Diagnostics.`;
  if (node.id === 'diagnostician') output = arr(state.queue).filter(item => obj(item).root_cause).map(item => `${textValue(item.id)}: ${textValue(item.root_cause)}`).join(' · ') || 'Not available';
  if (node.id === 'verify' && arr(state.fmea_compare).length) output = `${state.fmea_compare.length} published risk comparisons. See Recovery.`;
  if (node.id === 'reporter') output = textValue(state.report_path);
  return <section className="surface agent-guide" aria-labelledby="agent-guide-title"><SectionHeading id="agent-guide-title" eyebrow="UNDERSTAND THE TEAM" title={<>Purpose, inputs, and evidence <InfoTooltip term="agent roles" /></>} description="Descriptions explain the architecture. Published outputs below are separate from completion claims." />
    <div className="agent-guide-layout"><div className="agent-selector" role="group" aria-label="Select an agent or supporting step">{WORKFLOW_NODES.map(item => <button key={item.id} aria-pressed={selected === item.id} onClick={() => setSelected(item.id)}>{item.label}<small>{item.type === 'reasoning' ? 'Reasoning agent' : 'Supporting step'}</small></button>)}</div>
      <div className="agent-explanation"><h3>{node.label}</h3><dl className="detail-list"><div><dt>Purpose</dt><dd>{node.description}</dd></div><div><dt>Inputs · documented role</dt><dd>{INPUTS[node.id]}</dd></div><div><dt>Decisions · documented role</dt><dd>{DECISIONS[node.id]}</dd></div><div><dt>Workflow · allowed next steps</dt><dd><ul>{routes.map(route => <li key={route.to}><strong>{nodeLabel(route.to)}</strong> — {route.when}</li>)}</ul></dd></div><div><dt>Published output · completion is not inferred</dt><dd>{output}</dd></div></dl>
        <h4>Agent-attributed events</h4>{events.length ? <ul className="agent-evidence">{events.slice(-5).map((event, index) => <li key={index}><time>{localTime(event.t)}</time><p>{event.msg}</p></li>)}</ul> : <p className="missing-data">Not available</p>}
      </div>
    </div>
  </section>;
}

export function DiagnosticsDetails({ state }) {
  const causes = arr(state.queue).filter(item => typeof obj(item).root_cause === 'string' && item.root_cause.trim());
  return <div className="diagnostics-content"><section className="surface evidence-panel"><SectionHeading eyebrow="DIAGNOSIS" title={<>Reported root causes <InfoTooltip term="root cause" /></>} description="Backend explanations; confidence and fix success are not inferred." /><div className="panel-body">{causes.length ? causes.map((item, index) => <article className="reported-finding" key={index}><code>{textValue(item.id)}</code><h3>{textValue(item.name)}</h3><p>{item.root_cause}</p></article>) : <p className="missing-data">Not available</p>}
      <h3>Additional published findings</h3>{arr(state.findings).length ? <pre className="raw-evidence">{JSON.stringify(state.findings, null, 2)}</pre> : <p className="missing-data">Not available</p>}</div></section>
      <section className="surface evidence-panel"><SectionHeading eyebrow="MEASURED RISK" title={<>FMEA <InfoTooltip term="FMEA" /></>} description="Scores are produced by deterministic backend code." /><div className="panel-body">{arr(state.fmea).length ? <div className="data-table-scroll" role="region" tabIndex="0" aria-label="FMEA risk and evidence"><table className="evidence-table"><thead><tr><th>Failure mode</th><th>Effect</th><th>RPN <InfoTooltip term="RPN" /></th><th>Evidence</th></tr></thead><tbody>{state.fmea.map((raw, index) => { const row = obj(raw); return <tr key={index}><td><code>{textValue(row.id)}</code><strong>{textValue(row.failure_mode)}</strong></td><td>{textValue(row.effect)}</td><td>{fmt(row.rpn)}</td><td>{Array.isArray(row.evidence) ? row.evidence.length ? <ul>{row.evidence.map((evidence, i) => <li key={i}>{typeof evidence === 'string' ? evidence : JSON.stringify(evidence)}</li>)}</ul> : 'Not available' : row.evidence && typeof row.evidence === 'object' ? <ul>{Object.entries(row.evidence).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => <li key={k}>{k.replace(/_/g, ' ')}: {typeof v === 'number' && k === 'error_rate' ? `${Math.round(v * 100)}%` : typeof v === 'boolean' ? (v ? 'yes' : 'no') : Array.isArray(v) ? v.join(', ') || 'none' : String(v)}</li>)}</ul> : textValue(row.evidence)}</td></tr>; })}</tbody></table></div> : <p className="missing-data">Not available</p>}</div></section>
      <div className="concept-note"><strong>Know the terms</strong><span>Gray failure <InfoTooltip term="gray failure" /></span><span>Canary <InfoTooltip term="canary" /></span><small>Definitions only. Published Truth Oracle measurements are on Overview.</small></div>
  </div>;
}

export function RecoveryDetails({ state }) {
  const cleanup = obj(state.cleanup);
  return <section className="surface evidence-panel"><SectionHeading eyebrow="RECOVERY EVIDENCE" title="Confirmation comes from the backend" description="STOP acknowledgement, cleanup, and verified improvement are different states." /><div className="panel-body"><dl className="detail-list"><div><dt>Cleanup completion</dt><dd>{cleanup.done === true ? 'Backend marked cleanup done' : cleanup.done === false ? 'Backend reports cleanup incomplete' : 'Not available'}</dd></div><div><dt>Cleanup timestamp</dt><dd>{localTime(cleanup.at)}</dd></div><div><dt>Report path</dt><dd><code>{textValue(state.report_path)}</code></dd></div></dl>
    <h3>Reported faults</h3>{arr(state.faulted).length ? <ul>{state.faulted.map((raw, index) => { const fault = obj(raw); return <li key={index}>{textValue(fault.type)} · {textValue(fault.target)}</li>; })}</ul> : <p className="missing-data">{Array.isArray(state.faulted) ? 'No faults reported in this snapshot; restoration is not independently verified.' : 'Not available'}</p>}
    <h3>Measured risk comparisons <InfoTooltip term="RPN" /></h3>{arr(state.fmea_compare).length ? <div className="data-table-scroll" tabIndex="0" role="region" aria-label="Before and after risk"><table className="evidence-table"><thead><tr><th>Failure mode</th><th>RPN before</th><th>RPN after</th><th>Reduction (%)</th></tr></thead><tbody>{state.fmea_compare.map((raw, index) => { const row = obj(raw); return <tr key={index}><td>{textValue(row.failure_mode)} <code>{textValue(row.id)}</code></td><td>{fmt(row.rpn_before)}</td><td>{fmt(row.rpn_after)}</td><td>{fmt(row.reduction_pct)}</td></tr>; })}</tbody></table></div> : <p className="missing-data">Not available</p>}
    </div></section>;
}

export function HistoryPlaceholder() {
  return <section className="surface history-placeholder"><EmptyState icon="clock" title="Run history is not available yet">History browsing is not enabled yet. The run-history endpoints exist, but no archived runs, reports, or replay data are loaded in this view.</EmptyState><p className="history-note">Live status, STOP, and pending approvals above continue to refer to the current live run.</p></section>;
}
