import React, { createContext, useContext, useEffect, useState } from 'react';
import { controlApi } from '../api/controlApi.js';
import useControlRequest from '../hooks/useControlRequest.js';
import { obj, running } from '../data.js';
import StopConfirmationDialog from './StopConfirmationDialog.jsx';

const ControlContext = createContext(null);
export const useControls = () => useContext(ControlContext);

export default function ControlProvider({ live, children }) {
  const { state, status, refresh, received } = live;
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(timer); }, []);
  const connected = status === 'connected';
  const fresh = connected && typeof received === 'number' && now - received < 2000;
  // The adapter, not experiment id/name or an invented state field, must
  // validate and extract an authoritative gate/run identity.
  const gate = fresh && state.phase === 'running' && state.agent_active === 'human'
    && Object.keys(obj(state.approval_request)).length ? controlApi.getApprovalContext(state) : null;
  const run = fresh ? controlApi.getStopContext(state) : null;
  const approval = useControlRequest(gate?.key || null);
  const stop = useControlRequest(typeof state.run_dir === 'string' ? state.run_dir : null);
  const [dialog, setDialog] = useState({ open: false, key: null, runName: null });
  const stopAvailable = Boolean(run) && !stop.blocked;
  const approvalAvailable = Boolean(gate) && !approval.blocked && stop.result.status === 'idle';

  function decide(approved) {
    if (!approvalAvailable) return;
    approval.submit({
      key: gate.key, action: approved ? 'approve' : 'deny',
      request: signal => approved ? controlApi.approve(gate, { signal }) : controlApi.deny(gate, { signal }),
      onError: error => { if (error.status === 409) refresh?.(); },
      successMessage: `Backend acknowledged the ${approved ? 'approval' : 'denial'} decision. Waiting for the gate to update.`,
    });
  }

  function openStopDialog() {
    setDialog({ open: true, key: run?.key || null, runName: state.run_dir ? String(state.run_dir).split(/[\\/]/).pop() : null });
  }
  function confirmStop() {
    if (!stopAvailable || !dialog.open || dialog.key !== run.key) return;
    setDialog(previous => ({ ...previous, open: false }));
    stop.submit({
      key: run.key, action: 'stop',
      idempotent: true,
      request: signal => controlApi.requestStop(run, { signal, confirmed: true }),
      onError: error => { if (error.status === 409) refresh?.(); },
      successMessage: 'Backend acknowledged the STOP request. Run progress and cleanup confirmation are reported separately.',
    });
  }

  const value = { approvalAvailable, stopAvailable, approve: () => decide(true), deny: () => decide(false), openStopDialog, approvalResult: approval.result, stopResult: stop.result, now, backendApprovalResult: state.approval_result, runStatus: state.run_status, cleanup: state.cleanup, reportPath: state.report_path };
  return <ControlContext.Provider value={value}>{children}<StopConfirmationDialog open={dialog.open} runName={dialog.runName} available={stopAvailable && dialog.key === run?.key} onCancel={() => setDialog(previous => ({ ...previous, open: false }))} onConfirm={confirmStop} /></ControlContext.Provider>;
}
