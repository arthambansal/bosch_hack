import React from 'react';
import { timelineEvidence, TIMELINE_STAGES } from '../timelineModel.js';
import { timestamp } from '../truthModel.js';
import InfoTooltip from './InfoTooltip.jsx';
export default function ExperimentTimeline({ events }) {
  const markers = timelineEvidence(events);
  const missing = TIMELINE_STAGES.filter(stage => !markers.some(marker => marker.stage === stage));
  return <section className="evidence-timeline" aria-labelledby="timeline-title"><div className="section-heading"><div><span className="eyebrow">PUBLISHED RUN EVENTS</span><h2 id="timeline-title">Experiment evidence timeline</h2><p>Chronological order; spacing does not represent duration. Events are run-wide and are not automatically attributed to the current experiment.</p></div></div>
    {markers.length ? <ol className="timeline-track" aria-label="Timestamped experiment evidence">{markers.map(marker => <li key={marker.key}><InfoTooltip term={`${marker.stage} evidence`} triggerContent={<><strong>{marker.stage}</strong><time dateTime={new Date(marker.t * 1000).toISOString()}>{timestamp(marker.t)}</time><span>Inspect exact event</span></>} triggerClassName="timeline-marker">{marker.msg}</InfoTooltip></li>)}</ol> : <p>Not available — the backend has not published sufficient timestamped timeline evidence.</p>}
    {missing.length > 0 && <p className="timeline-note">Not available: {missing.join(', ')}. No timestamps are inferred from phase, guard status, or elapsed durations.</p>}
    <p className="timeline-note">Probe recovery records the backend’s probe result. A successful restore command alone does not confirm service recovery.</p>
    {markers.length > 0 && <details><summary>Exact timeline evidence</summary><ol>{markers.map(marker => <li key={marker.key}><time>{timestamp(marker.t)}</time> · {marker.msg}</li>)}</ol></details>}
  </section>;
}
