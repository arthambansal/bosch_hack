import React from 'react';
import { obj, arr, num, localTime } from '../data.js';
import { Icon } from './ui.jsx';
import { useControls } from './ControlProvider.jsx';
import ControlFeedback from './ControlFeedback.jsx';
import { APPROVAL_BLOCKER } from '../api/controlApi.js';

export default function ApprovalPanel({ request, phase, connected }) {
  const req = obj(request), pending = Object.keys(req).length > 0;
  const controls = useControls(), result = controls?.approvalResult;
  const loading = result?.status === 'loading';
  const now = (controls?.now || Date.now()) / 1000;
  const expired = num(req.expires_at) && req.expires_at <= now;
  const completed = obj(controls?.backendApprovalResult);
  const validResult = ['approved', 'denied'].includes(completed.answer) && typeof completed.gate_id === 'string';
  return <section className={`approval-panel ${pending ? 'has-request' : ''}`} aria-labelledby="approval-title"><div className="control-subheading"><h3 id="approval-title">Human approval</h3><span>{pending ? expired ? 'Expired' : connected && phase === 'running' ? 'Pending question' : 'Last reported request' : 'No pending request'}</span></div>
    {pending ? <div className="approval-request"><code>{req.id} · {req.gate_id || 'No gate token'}</code><strong>{req.name || 'Approval requested'}</strong>{req.question && <p className="approval-question">{req.question}</p>}<p>{req.reason || 'No reason supplied.'}</p>
      {arr(req.steps).length > 0 && <ul className="approval-steps">{req.steps.map((step, index) => <li key={index}>{String(obj(step).type || 'Fault')} → {String(obj(step).target || 'Unknown target')}</li>)}</ul>}
      <small>{num(req.expires_at) ? `Expires ${new Date(req.expires_at * 1000).toLocaleTimeString([], { hour12: false })}${expired ? ' · expired' : ` · ${Math.max(0, Math.ceil(req.expires_at - now))} s remaining`}` : 'Expiry unavailable'}</small>
      {(!connected || phase !== 'running') && <small>Current request status is unconfirmed.</small>}</div> : <p className="approval-empty">When an experiment needs your decision, its request will appear here.</p>}
    <div className="approval-actions" aria-busy={loading}><button disabled={!controls?.approvalAvailable} onClick={controls?.approve}><Icon name="check" size={16} />{loading && result.action === 'approve' ? 'Sending…' : 'Approve'}</button><button disabled={!controls?.approvalAvailable} onClick={controls?.deny}>{loading && result.action === 'deny' ? 'Sending…' : 'Deny'}</button></div>
    <ControlFeedback result={result} />
    <p className="unavailable-note"><Icon name="lock" size={13} />{APPROVAL_BLOCKER}</p>
    {validResult && <div className="backend-approval-result" role="status"><strong>Backend decision: {completed.answer}</strong><small>Gate {completed.gate_id} · {String(completed.source || 'Source unavailable')} · {localTime(completed.at)}</small></div>}
  </section>;
}
