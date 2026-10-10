import React from 'react';
import { obj, running } from '../data.js';
import { Icon } from './ui.jsx';

export default function ApprovalPanel({ request, phase, connected }) {
  const req = obj(request), pending = Object.keys(req).length > 0;
  return <section className={`approval-panel ${pending ? 'has-request' : ''}`} aria-labelledby="approval-title"><div className="control-subheading"><h3 id="approval-title">Human approval</h3><span>{pending ? connected && running(phase) ? 'Request reported' : 'Last reported request' : 'No pending request'}</span></div>
    {pending ? <div className="approval-request"><code>{req.id}</code><strong>{req.name || 'Approval requested'}</strong><p>{req.reason || 'No reason supplied.'}</p>{(!connected || !running(phase)) && <small>Current request status is unconfirmed.</small>}</div> : <p className="approval-empty">When an experiment needs your decision, its request will appear here.</p>}
    <div className="approval-actions"><button disabled><Icon name="check" size={16} />Approve</button><button disabled>Deny</button></div><p className="unavailable-note"><Icon name="lock" size={13} />Dashboard approval actions are not connected.</p>
  </section>;
}
