import React from 'react';
import useLiveState from './hooks/useLiveState.js';
import WorkspaceShell from './components/WorkspaceShell.jsx';
import RunOverview from './components/RunOverview.jsx';
import AgentWorkflow from './components/AgentWorkflow.jsx';
import DependencyMap from './components/DependencyMap.jsx';
import ActivityFeed from './components/ActivityFeed.jsx';
import TelemetryPanel from './components/TelemetryPanel.jsx';
import SafetyPanel from './components/SafetyPanel.jsx';
import { Icon } from './components/ui.jsx';

export default function App() {
  const { state, status, error, received } = useLiveState();
  const connected = status === 'connected';
  return <WorkspaceShell status={status} received={received}>
    <RunOverview state={state} connected={connected} loading={status === 'loading'} />
    <div className="provenance-note"><Icon name="info" size={15} /><p><strong>Snapshot data.</strong> Measurement provenance is not supplied. These values may come from mock runs and are not verified Docker measurements.</p></div>
    {error && <div className="connection-alert" role="status"><Icon name="info" /><p>{error}</p></div>}
    <AgentWorkflow state={state} connected={connected} />
    <div className="observability-grid"><DependencyMap state={state} connected={connected} /><TelemetryPanel state={state} connected={connected} /></div>
    <div className="operations-grid"><ActivityFeed events={state.events} /><SafetyPanel state={state} connected={connected} /></div>
  </WorkspaceShell>;
}
