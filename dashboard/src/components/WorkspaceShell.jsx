import React, { useState } from 'react';
import { Icon } from './ui.jsx';
import { StopControl } from './SafetyPanel.jsx';

const navigation = [
  ['overview', 'Overview', 'overview'], ['workflow', 'Agent workflow', 'workflow'],
  ['topology', 'Application map', 'topology'], ['telemetry', 'Telemetry', 'telemetry'],
  ['activity', 'Activity', 'activity'], ['controls', 'Safety & approvals', 'shield'],
];

export default function WorkspaceShell({ status, received, children }) {
  const [section, setSection] = useState('overview');
  const connected = status === 'connected';
  return <div className="app-shell">
    <a href="#main-content" className="skip-link">Skip to dashboard</a>
    <aside className="sidebar">
      <a className="brand" href="#overview" aria-label="ChaosPilot overview"><span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M6 23L15 5l3 11 8-7-9 18-3-11Z" fill="currentColor" /></svg></span><span>ChaosPilot<span className="brand-subtitle">RESILIENCE WORKSPACE</span></span></a>
      <div className="workspace-switch"><span className="workspace-avatar">CP</span><div><strong>Control room</strong><small>Local workspace</small></div></div>
      <span className="nav-label">WORKSPACE</span>
      <nav aria-label="Dashboard sections">{navigation.map(([id, label, icon]) => <a key={id} href={`#${id}`} aria-label={label} className={section === id ? 'selected' : ''} aria-current={section === id ? 'location' : undefined} onClick={() => setSection(id)}><Icon name={icon} size={18} /><span>{label}</span>{section === id && <span className="nav-marker" />}</a>)}</nav>
      <div className="sidebar-bottom"><div className="sandbox-note"><Icon name="shield" size={21} /><strong>Controlled by design.</strong><p>Experiments, evidence, and recovery in one workspace.</p></div><div className="sidebar-foot"><span className="local-dot" />Local backend</div></div>
    </aside>
    <div className="workspace-main">
      <header className="topbar"><div className="breadcrumb">Workspace<Icon name="chevron" size={14} /><strong>Control room</strong></div><div className="topbar-actions"><span className={`connection-status ${connected ? 'connected' : status === 'loading' ? '' : 'error'}`} role="status" aria-live="polite"><i />{connected ? 'Backend connected' : status === 'loading' ? 'Connecting' : status === 'malformed' ? 'Invalid state' : 'Disconnected'}</span><span className="read-only-label">READ ONLY</span><StopControl compact /></div></header>
      <main id="main-content">{children}</main>
      <footer className="workspace-footer"><span>ChaosPilot <i /> Evidence before assumptions.</span><span>{received ? `Snapshot received ${new Date(received).toLocaleTimeString([], { hour12: false })}` : 'Waiting for a state snapshot'} · 500 ms polling</span></footer>
    </div>
  </div>;
}
