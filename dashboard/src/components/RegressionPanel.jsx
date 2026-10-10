import React from 'react';
import { regressionRows } from '../historyModel.js';
export default function RegressionPanel({ value, stale }) {
  const rows = regressionRows(value);
  return <section className="surface p1-panel"><div className="panel-body"><h2>Regression scenarios</h2><p className="p1-note">A regression is a previously confirmed failure returning. An invariant is a condition a replay checks. Status describes the last backend replay; it does not establish current recovery.{stale && ' Retained snapshot — current status is unconfirmed.'}</p>
    {!rows ? <p>Not available</p> : !rows.length ? <p>No regression scenarios published. Recovery and absence of regression are unconfirmed.</p> : <div className="data-table-scroll" tabIndex="0" role="region" aria-label="Published regression scenarios"><table className="evidence-table"><thead><tr><th>Scenario / file</th><th>Invariant</th><th>Last replay</th><th>Published timestamp (UTC)</th></tr></thead><tbody>{rows.map((row,i)=><tr key={i}><td>{row.id}<br/><code>{row.file}</code></td><td>{row.invariant}</td><td>{row.status}</td><td>{row.at}</td></tr>)}</tbody></table></div>}
  </div></section>;
}
