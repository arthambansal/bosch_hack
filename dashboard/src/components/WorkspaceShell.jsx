import React, { useEffect, useRef, useState } from 'react';
import { VIEWS, nextTabIndex } from '../viewModel.js';
import { Icon } from './ui.jsx';
import LiveStatusStrip from './LiveStatusStrip.jsx';

export default function WorkspaceShell({ live, view, onView, approvalOpen, onApproval, approvalContent, children }) {
  const [presentation,setPresentation]=useState(false);
  const tabs = useRef([]);
  const root = useRef(null), header = useRef(null);
  useEffect(() => {
    const measure = () => root.current?.style.setProperty('--global-header-height', `${header.current.getBoundingClientRect().height}px`);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(header.current);
    return () => observer.disconnect();
  }, []);
  const fixture = live.source === 'fixture';
  const connected = !fixture && live.status === 'connected';
  function navigateKey(event, index) {
    const next = nextTabIndex(index, event.key);
    if (next !== null) { event.preventDefault(); tabs.current[next]?.focus(); }
  }
  return <div ref={root} className={`app-shell control-room-v2${presentation?' presentation-mode':''}`}>
    <a href="#main-content" className="skip-link">Skip to dashboard</a>
    <div ref={header} className="global-header">
      <header className="product-header"><button className="brand" onClick={() => onView('overview')} aria-label="ChaosPilot overview"><span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M6 23L15 5l3 11 8-7-9 18-3-11Z" fill="currentColor" /></svg></span><span>ChaosPilot<span className="brand-subtitle">CONTROL ROOM / LOCAL WORKSPACE</span></span></button>
        <nav className="top-navigation" aria-label="Control Room views"><div role="tablist" aria-label="Dashboard views">{VIEWS.map((item, index) => <button key={item.id} ref={element => { tabs.current[index] = element; }} role="tab" id={`tab-${item.id}`} aria-controls={`view-${item.id}`} aria-selected={view === item.id} tabIndex={view === item.id ? 0 : -1} onKeyDown={event => navigateKey(event, index)} onClick={() => onView(item.id)}><Icon name={item.icon} size={17} />{item.label}</button>)}</div></nav>
        <button type="button" className="presentation-toggle" aria-pressed={presentation} onClick={()=>setPresentation(value=>!value)}>{presentation?'Exit Presentation Mode':'Presentation Mode'}</button>
        <span className={`connection-status ${connected ? 'connected' : live.status === 'loading' ? '' : 'error'}`} role="status"><i />{fixture ? 'FIXTURE DATA' : connected ? 'Backend connected' : live.status === 'loading' ? 'Connecting' : live.status === 'malformed' ? 'Invalid state' : 'Disconnected'}</span>
      </header>
      <LiveStatusStrip live={live} approvalOpen={approvalOpen} onApproval={onApproval} />
    </div>
    <aside id="global-approval" className="global-approval" hidden={!approvalOpen} aria-label="Global approval controls"><div className="drawer-heading"><strong>Human oversight · {fixture ? 'fixture controls disabled' : 'current live gate'}</strong><button type="button" className="text-button" onClick={onApproval}>Close approval panel</button></div>{approvalContent}</aside>
    <main id="main-content" tabIndex="-1">{children}</main>
    <footer className="workspace-footer"><span>ChaosPilot <i /> Evidence before assumptions.</span><span>{fixture ? `Static fixture: ${live.fixtureName || 'Not available'} · mutations and live polling disabled` : <>{live.received ? `Snapshot received ${new Date(live.received).toLocaleTimeString([], { hour12: false })}` : 'Waiting for a state snapshot'} · 500 ms polling</>}</span></footer>
  </div>;
}
