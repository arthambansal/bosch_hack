import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { controlApi, liveApprovalContext } from '../api/controlApi.js';
import useControlRequest from '../hooks/useControlRequest.js';
import { day2Api } from '../api/day2Api.js';
import { mysteryIdentity, mysterySubmissionContext, mysteryConfirmationValid } from '../p1Model.js';
import MysteryConfirmationDialog from './MysteryConfirmationDialog.jsx';
import StopConfirmationDialog from './StopConfirmationDialog.jsx';

const ControlContext = createContext(null);
export const useControls = () => useContext(ControlContext);

export default function ControlProvider({ live, children }) {
  const { state, status, refresh, received } = live;
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(timer); }, []);
  const connected = live.source !== 'fixture' && status === 'connected';
  const fresh = connected && typeof received === 'number' && now - received < 2000;
  // The adapter, not experiment id/name or an invented state field, must
  // validate and extract an authoritative gate/run identity.
  const stopRequested = useRef(false);
  const stopRun = useRef(state.run_dir);
  if (stopRun.current !== state.run_dir) { stopRun.current = state.run_dir; stopRequested.current = false; }
  const gate = liveApprovalContext(live, stopRequested.current, now);
  const run = fresh ? controlApi.getStopContext(state) : null;
  const approval = useControlRequest(gate?.key || null);
  const stop = useControlRequest(typeof state.run_dir === 'string' ? state.run_dir : null);
  const mystery = useControlRequest(mysteryIdentity(state));
  const mutationSlot = useRef(null);
  const latestLive = useRef(live); latestLive.current = live;
  const [confirmation, setConfirmation] = useState({open:false, signature:null, choice:null, label:null});
  const [dialog, setDialog] = useState({ open: false, key: null, runName: null });
  const stopAvailable = Boolean(run) && !stop.blocked;
  const approvalAvailable = Boolean(gate) && !approval.blocked && stop.result.status === 'idle' && mystery.result.status !== 'loading' && !confirmation.open;
  const conflicts = { stopRequested: stopRequested.current, pending: approval.result.status === 'loading' || stop.result.status !== 'idle' || mystery.result.status === 'loading', dialogOpen: dialog.open };
  const mysteryGate = mysterySubmissionContext(live, conflicts, now);
  const mysteryAvailable = Boolean(mysteryGate) && !mystery.blocked;
  const latestConflicts = useRef(conflicts); latestConflicts.current = conflicts;

  function decide(approved) {
    if (!approvalAvailable || mutationSlot.current) return;
    const current = liveApprovalContext(live, stopRequested.current);
    if (!current || current.key !== gate.key) return;
    mutationSlot.current = 'approval';
    approval.submit({
      key: current.key, action: approved ? 'approve' : 'deny',
      request: signal => approved ? controlApi.approve(current, { signal }) : controlApi.deny(current, { signal }),
      onError: error => { if (error.status === 409 || error.status === 503) refresh?.(); },
      successMessage: `Backend acknowledged the ${approved ? 'approval' : 'denial'} decision. Waiting for the gate to update.`,
    }).finally(() => { if (mutationSlot.current === 'approval') mutationSlot.current = null; });
  }

  function openStopDialog() {
    setConfirmation(previous=>({...previous,open:false}));
    setDialog({ open: true, key: run?.key || null, runName: state.run_dir ? String(state.run_dir).split(/[\\/]/).pop() : null });
  }
  function confirmStop() {
    if (!stopAvailable || !dialog.open || dialog.key !== run.key) return;
    stopRequested.current = true;
    setDialog(previous => ({ ...previous, open: false }));
    stop.submit({
      key: run.key, action: 'stop',
      idempotent: true,
      request: signal => controlApi.requestStop(run, { signal, confirmed: true }),
      onError: error => { if (error.status === 409) refresh?.(); },
      successMessage: 'Backend acknowledged the STOP request. Run progress and cleanup confirmation are reported separately.',
    });
  }

  function currentMysteryGate() {
    return mysterySubmissionContext(latestLive.current, {...latestConflicts.current, stopRequested: stopRequested.current, pending: latestConflicts.current.pending || Boolean(mutationSlot.current)});
  }
  function openMysteryDialog(choice) {
    const current = currentMysteryGate();
    if (!mysteryAvailable || !current || (choice !== 'random' && !current.menu.some(item=>item.id===choice))) return;
    setConfirmation({open:true,choice,signature:current.signature,label:choice==='random'?'Random allowed fault':current.menu.find(item=>item.id===choice).label});
  }
  function confirmMystery() {
    const current = currentMysteryGate();
    if (!mysteryAvailable || !mysteryConfirmationValid(confirmation,current)) return;
    mutationSlot.current = 'mystery';
    setConfirmation(previous=>({...previous,open:false}));
    mystery.submit({key:current.key,action:'mystery',
      request:signal=>day2Api.requestMystery(confirmation.choice,latestLive.current,{signal,stopRequested:stopRequested.current}),
      onError:error=>{if(error.status===400 || error.status===409 || error.status===503 || error.uncertain) refresh?.();},
      successMessage:'Backend accepted the Mystery request. Injection and trial completion remain unconfirmed; follow the published state.',
    }).finally(()=>{if(mutationSlot.current==='mystery')mutationSlot.current=null;});
  }

  const value = { mysteryAvailable, openMysteryDialog, mysteryResult: mystery.result, approvalAvailable, stopAvailable, approve: () => decide(true), deny: () => decide(false), openStopDialog, approvalResult: approval.result, stopResult: stop.result, now, backendApprovalResult: state.approval_result, runStatus: state.run_status, cleanup: state.cleanup, reportPath: state.report_path };
  return <ControlContext.Provider value={value}>{children}<StopConfirmationDialog open={dialog.open} runName={dialog.runName} available={stopAvailable && dialog.key === run?.key} onCancel={() => setDialog(previous => ({ ...previous, open: false }))} onConfirm={confirmStop} /><MysteryConfirmationDialog confirmation={confirmation} available={mysteryAvailable && mysteryConfirmationValid(confirmation,mysteryGate)} onCancel={()=>setConfirmation(previous=>({...previous,open:false}))} onConfirm={confirmMystery} /></ControlContext.Provider>;
}
