import React, { useEffect, useState } from 'react';
import { fixtureSelection } from './fixtures.js';
import useFixtureState from './hooks/useFixtureState.js';
import TruthPanel from './components/TruthPanel.jsx';
import ExperimentTimeline from './components/ExperimentTimeline.jsx';
import useLiveState from './hooks/useLiveState.js';
import WorkspaceShell from './components/WorkspaceShell.jsx';
import RunOverview from './components/RunOverview.jsx';
import AgentWorkflow from './components/AgentWorkflow.jsx';
import DependencyMap from './components/DependencyMap.jsx';
import ActivityFeed from './components/ActivityFeed.jsx';
import TelemetryPanel from './components/TelemetryPanel.jsx';
import SafetyPanel from './components/SafetyPanel.jsx';
import ApprovalPanel from './components/ApprovalPanel.jsx';
import { MysteryPanel, FixesPanel, MemoryPanel, PlanPanel, PredictionsPanel, ImpactPanel } from './components/P1Panels.jsx';
import { Icon } from './components/ui.jsx';
import ControlProvider from './components/ControlProvider.jsx';
import HistoryPanel from './components/HistoryPanel.jsx';
import RegressionPanel from './components/RegressionPanel.jsx';
import { VIEWS } from './viewModel.js';
import InfoTooltip, { TooltipScope } from './components/InfoTooltip.jsx';
import { ViewHeading, ExperimentDetails, AgentGuide, DiagnosticsDetails, RecoveryDetails } from './components/ControlRoomViews.jsx';

export function DashboardWorkspace({ live }) {
  const [view, setView] = useState('overview');
  const [approvalOpen, setApprovalOpen] = useState(false);
  const { state, status, error } = live;
  const connected = live.source !== 'fixture' && status === 'connected';
  const gateId = state.approval_request?.gate_id;
  useEffect(() => { if (gateId) setApprovalOpen(true); }, [gateId]);
  const panels = {
    overview: <><TruthPanel truth={state.truth} /><RunOverview state={state} connected={connected} loading={status === 'loading'} /><div className="overview-grid"><TelemetryPanel state={state} connected={connected} /><SafetyPanel state={state} connected={connected} /></div><ActivityFeed events={state.events} /></>,
    agents: <><ViewHeading title="Agents">Understand the reasoning, the safeguards, and the evidence each step publishes.</ViewHeading><AgentWorkflow state={state} connected={connected} /><div className="agents-grid"><AgentGuide state={state} /><DependencyMap state={state} connected={connected} /></div></>,
    experiments: <><ViewHeading title="Experiments">Intent, fault steps, reported outcomes, and observed signals.</ViewHeading><MysteryPanel live={live} /><div className="p1-grid"><PlanPanel plan={state.plan_ranking} /><ImpactPanel impact={state.impact} /></div><PredictionsPanel predictions={state.predictions} /><div className="observability-grid"><ExperimentDetails state={state} /><TelemetryPanel state={state} connected={connected} id="experiment-telemetry" /></div><ExperimentTimeline events={state.events} /></>,
    diagnostics: <><ViewHeading title="Diagnostics">Reported causes and measured risk, grounded in published evidence.</ViewHeading><MemoryPanel memory={state.memory} /><DiagnosticsDetails state={state} /><RemediationSummary fixes={state.fixes} onRecovery={()=>setView('recovery')} /></>,
    recovery: <><ViewHeading title="Recovery">Follow backend cleanup and measured risk comparisons.</ViewHeading><div className="recovery-grid"><RecoveryDetails state={state} /><SafetyPanel state={state} connected={connected} id="recovery-controls" /></div><RegressionPanel value={state.regression} stale={live.source !== 'fixture' && (!connected || !Number.isFinite(live.received) || Date.now()-live.received>=2000)} /><FixesPanel fixes={state.fixes} /></>,
    history: <><ViewHeading title="History">Recorded evidence. Global controls remain attached to the current live run.</ViewHeading><HistoryPanel active={view==='history'} fixture={live.source==='fixture'} /></>,
  };
  return <TooltipScope.Provider value={view}><WorkspaceShell live={live} view={view} onView={setView} approvalOpen={approvalOpen} onApproval={() => setApprovalOpen(previous => !previous)} approvalContent={<ApprovalPanel request={state.approval_request} phase={state.phase} connected={connected} />}>
    <ProvenanceNote live={live} />
    {error && <div className="connection-alert" role="status"><Icon name="info" /><p>{error}</p></div>}
    {/* Retain component state (event filters, node selections) across navigation.
        Polling and the control provider live above these persistent panels. */}
    {VIEWS.map(item => <div key={item.id} id={`view-${item.id}`} role="tabpanel" aria-labelledby={`tab-${item.id}`} tabIndex="0" hidden={view !== item.id}>{panels[item.id]}<ViewTerms view={item.id} /></div>)}
  </WorkspaceShell></TooltipScope.Provider>;
}

const VIEW_TERMS = {
  overview: ['Truth Oracle', 'gray failure', 'canary votes', 'invariants', 'p95 latency', 'error rate', 'baseline', 'safety thresholds', 'kill switch', 'Provenance', 'probes', 'canary grace', 'approval gate'],
  agents: ['agent roles', 'Governor', 'blast radius', 'Provenance', 'stateful'],
  experiments: ['Confidence', 'Memory hit', 'risk score', 'prediction check', 'MTTD', 'MTTR', 'p95 latency', 'baseline', 'fault injection', 'delivery'],
  diagnostics: ['root cause', 'Confidence', 'Similarity', 'Memory hit', 'FMEA', 'RPN', 'signature'],
  recovery: ['Rollback', 'verification status', 'Untested fixes', 'Regression', 'RPN', 'safety thresholds', 'kill switch', 'healing', 'compose'],
  history: ['event replay', 'Provenance', 'verification status', 'resilience score'],
};
function ViewTerms({ view }) {
  return <details className="surface technical-terms"><summary>Understand this view · technical terms</summary><div>{VIEW_TERMS[view].map(term=><span key={term}>{term} <InfoTooltip term={term} /></span>)}</div></details>;
}
export function RemediationSummary({ fixes, onRecovery }) {
  const records=Array.isArray(fixes)?fixes:[];
  const failures=records.filter(fix=>fix?.rollback_failed===true).length;
  const untested=records.filter(fix=>Array.isArray(fix?.untested)&&fix.untested.length>0).length;
  return <section className="surface remediation-summary" aria-label="Recovery evidence summary"><div><h2>Continue to Recovery</h2><p>{Array.isArray(fixes)?`${records.length} published fix records`:'Fix evidence not available'}. Detailed remediation, comparisons, and verification are in Recovery.</p>{failures>0 && <p className="critical-text">{failures} rollback failure records — recovery is unconfirmed.</p>}{untested>0 && <p>{untested} fix records contain experiments not re-tested.</p>}</div><button type="button" className="p1-primary" onClick={onRecovery}>View recovery evidence</button></section>;
}

export function provenanceText(live) {
  if (live.source === 'fixture') return { tone: 'fixture', title: 'FIXTURE DATA — static demonstration snapshot.', body: 'Not a measurement.' };
  const p = live.state && typeof live.state.provenance === 'object' && live.state.provenance ? live.state.provenance : null;
  if (!p || p.measurements !== 'docker_sandbox') return { tone: 'unknown', title: 'Snapshot data.', body: 'Measurement provenance is not supplied. These values may come from mock runs and are not verified Docker measurements.' };
  const ai = p.ai && typeof p.ai === 'object' ? p.ai : {};
  const aiText = ai.mode === 'live' ? `AI live: ${ai.provider || 'provider'} ${ai.model || ''}`.trim()
    : ai.mode === 'cached' ? 'AI: replaying cached answers (--offline)'
    : ai.mode === 'off' ? 'AI OFF: no API key, agents use deterministic rules' : 'AI status not reported';
  return { tone: ai.mode === 'off' ? 'warn' : 'live', title: `LIVE measurements from Docker sandbox "${p.project || 'sandbox'}".`, body: aiText + '.' };
}

function ProvenanceNote({ live }) {
  const t = provenanceText(live);
  return <div className={`provenance-note provenance-${t.tone}`}><Icon name="info" size={15} /><p><strong>{t.title}</strong> <InfoTooltip term="Provenance" /> {t.body}</p></div>;
}

function LiveSession() {
  const live = useLiveState();
  return <ControlProvider live={live}><DashboardWorkspace live={live} /></ControlProvider>;
}

function FixtureSession({ selection }) {
  const live = useFixtureState(selection);
  return <ControlProvider live={live}><DashboardWorkspace live={live} /></ControlProvider>;
}
export default function App() {
  const [selection] = useState(() => fixtureSelection(typeof window === 'undefined' ? '' : window.location.search));
  return selection ? <FixtureSession selection={selection} /> : <LiveSession />;
}
