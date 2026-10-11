import React from 'react';
import { truthPresentation } from '../truthModel.js';
import InfoTooltip from './InfoTooltip.jsx';
export default function TruthPanel({ truth }) {
  const data = truthPresentation(truth);
  return <section className={`truth-hero truth-${data.status || 'missing'}`} aria-labelledby="truth-title">
    <div className="truth-heading"><div><span className="eyebrow">END-TO-END EVIDENCE</span><h2 id="truth-title">Truth vs Monitoring</h2><p>Reported health checks and application correctness, shown independently.</p></div><InfoTooltip term="gray failure" /></div>
    <div className="truth-indicators"><div><span>Monitoring <InfoTooltip term="monitoring" /></span><strong>{data.monitoring || 'Not available'}</strong></div><div><span>Truth Oracle <InfoTooltip term="Truth Oracle" /></span><strong>{data.status || 'Not available'}</strong></div></div>
    {data.status === 'diverged' && <div className="gray-warning" role="status"><strong>GRAY FAILURE</strong><span>{data.monitoring === 'healthy' ? 'Monitoring appears healthy while application correctness has diverged.' : 'The backend reports divergence; its monitoring field is missing or inconsistent.'}</span><span>Diverged at: {data.divergedAt}</span></div>}
    {data.inconsistent && <p className="critical-text">Inconsistent backend snapshot: diverged requires healthy monitoring. Reported fields are shown without inferring health.</p>}
    <div className="truth-measurements"><h3>Canary votes <InfoTooltip term="canary votes" /></h3><dl>{[['sent','Sent'],['stored','Stored'],['pending','Pending'],['suspected_lost','Suspected lost'],['last_lag_s','Last lag (s)'],['grace_s','Grace (s)']].map(([key,label]) => <div key={key}><dt>{label}</dt><dd>{data.canaries[key]}</dd></div>)}</dl></div>
    <div className="truth-invariants"><h3>Invariants <InfoTooltip term="invariants" /></h3>{data.invariants.length ? <ul>{data.invariants.map((item,index) => <li key={index} className={item.status === 'Failing' ? 'invariant-failing' : ''}><strong>{item.name}</strong><span>{item.status}</span><p>{item.detail}</p></li>)}</ul> : <p>Not available — no invariant measurements published.</p>}</div>
    <p className="truth-footnote">Oracle updated: {data.updatedAt}. These are reported snapshot values; receipt of a snapshot does not establish measurement freshness.</p>
  </section>;
}
