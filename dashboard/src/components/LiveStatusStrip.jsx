import React from 'react';
import { statusPresentation } from '../viewModel.js';
import { useControls } from './ControlProvider.jsx';
import ControlFeedback from './ControlFeedback.jsx';
import InfoTooltip from './InfoTooltip.jsx';
import { StopControl } from './SafetyPanel.jsx';

export default function LiveStatusStrip({ live, approvalOpen, onApproval }) {
  const controls = useControls(), status = statusPresentation(live, controls?.now);
  const pending = Boolean(live.state.approval_request);
  return <div className={`live-strip ${status.fresh ? '' : 'snapshot-stale'}`}>
    <dl className="live-readouts" aria-label="Global run and safety status">
      <div><dt>{status.fresh ? 'Run status' : 'Last run status'}</dt><dd>{status.run}</dd></div>
      <div><dt>Phase</dt><dd>{status.phase}</dd></div>
      <div><dt>Active agent</dt><dd>{status.agent}</dd></div>
      <div className="experiment-readout"><dt>{status.experimentCurrent ? 'Current experiment' : 'Last experiment'}</dt><dd>{status.experiment}</dd></div>
      <div><dt>Guard <InfoTooltip term="guard ticks" /></dt><dd className={status.guard === 'Tripped' ? 'critical-text' : ''}>{status.guard}</dd></div>
    </dl>
    <div className="global-control-actions"><button type="button" className={`approval-access ${pending ? 'pending' : ''}`} aria-expanded={approvalOpen} aria-controls="global-approval" onClick={onApproval}>{pending ? 'Approval request' : 'Approvals'}{pending && <span>{controls?.approvalAvailable ? 'Decision needed' : 'Review status'}</span>}</button><StopControl compact /></div>
    {!status.fresh && <p className="strip-stale-note">{live.status === 'loading' ? 'Waiting for live state.' : 'Snapshot is stale or disconnected. Current activity is unconfirmed.'}</p>}
    <div className="global-stop-feedback"><ControlFeedback result={controls?.stopResult} /></div>
    <p id="stop-note" className="sr-only">STOP requests cancellation and cleanup. Acknowledgement does not confirm cleanup completion.</p>
  </div>;
}
