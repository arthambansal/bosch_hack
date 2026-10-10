import React, { useMemo, useState } from 'react';
import { arr, obj, localTime } from '../data.js';
import { EmptyState, Icon, SectionHeading } from './ui.jsx';

export default function ActivityFeed({ events }) {
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [newest, setNewest] = useState(true);
  const rows = useMemo(() => arr(events).filter(raw => {
    const event = obj(raw);
    return (filter === 'all' || (filter === 'ai' ? event.kind === 'ai' : ['guard', 'restore', 'warn'].includes(event.kind))) && String(event.msg || '').toLowerCase().includes(query.toLowerCase());
  }).slice().sort((a, b) => ((Number(a?.t) || 0) - (Number(b?.t) || 0)) * (newest ? -1 : 1)), [events, filter, query, newest]);

  return <section className="surface activity-panel" id="activity" aria-labelledby="activity-title">
    <SectionHeading id="activity-title" eyebrow="THE EVIDENCE TRAIL" title="Every decision leaves a trace" description="Emitted events and explanations, as reported by the backend."><span className="section-count">{arr(events).length} events</span></SectionHeading>
    <div className="activity-toolbar"><div className="segmented" aria-label="Filter events">{[['all', 'All events'], ['ai', 'Agents'], ['safety', 'Safety']].map(([value, label]) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}</div><button className="text-button" onClick={() => setNewest(!newest)}>{newest ? 'Newest first' : 'Oldest first'} <span aria-hidden="true">↕</span></button></div>
    <label className="event-search"><Icon name="search" size={16} /><span className="sr-only">Search event messages</span><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Find something in the evidence…" /></label>
    <div className="event-feed" tabIndex="0" role="region" aria-label="Operational event timeline">
      {rows.length ? rows.map((raw, index) => {
        const event = obj(raw), kind = ['info', 'inject', 'guard', 'restore', 'ai', 'ok', 'warn'].includes(event.kind) ? event.kind : 'info';
        return <article className={`event-row kind-${kind}`} key={`${event.t}-${index}`}><time>{localTime(event.t)}</time><div className="event-track"><i /></div><div className="event-content"><span className="event-kind">{typeof event.kind === 'string' ? event.kind : 'event'}</span><p>{String(event.msg ?? '').replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '')}</p></div></article>;
      }) : <EmptyState icon="activity" title={query ? 'No matching evidence' : 'No events to display'}>{query ? 'Try another search term or select a different event filter.' : 'The next reported event will appear here. No activity is simulated.'}</EmptyState>}
    </div>
    <div className="panel-foot"><small>Local timestamps · last 60 backend events</small><small>Explanations, not private reasoning traces</small></div>
  </section>;
}
