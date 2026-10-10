import React, { useEffect, useRef } from 'react';
import { Icon } from './ui.jsx';

export default function StopConfirmationDialog({ open, runName, available, onCancel, onConfirm }) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog = ref.current;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
    return () => { if (dialog.open) dialog.close(); };
  }, [open]);

  return <dialog ref={ref} className="stop-dialog" aria-labelledby="stop-dialog-title" aria-describedby="stop-dialog-description" onCancel={event => { event.preventDefault(); onCancel(); }}>
    <div className="stop-dialog-heading"><Icon name="stop" size={25} /><div><span className="eyebrow">EMERGENCY CONTROL</span><h2 id="stop-dialog-title">Request a stop for this run?</h2></div></div>
    <p id="stop-dialog-description">This requests cancellation and cleanup. An active AI call may delay cancellation. Acknowledgement does not mean that cleanup or the partial report has finished.</p>
    <div className="stop-dialog-run"><small>Run in view</small><code>{runName || 'No run identified'}</code></div>
    {!available && <p className="stop-dialog-unavailable">Submission is unavailable until the STOP endpoint, request contract, and cancellation handling are verified. Reviewing this dialog sends no request.</p>}
    <div className="stop-dialog-actions"><button autoFocus onClick={onCancel}>Cancel</button><button className="stop-button" disabled={!available} onClick={onConfirm}><Icon name="stop" size={16} />Confirm STOP request</button></div>
  </dialog>;
}
