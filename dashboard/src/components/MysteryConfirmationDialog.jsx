import React, { useEffect, useRef } from 'react';
export default function MysteryConfirmationDialog({ confirmation, available, onCancel, onConfirm }) {
  const ref=useRef(null);
  useEffect(()=>{
    const dialog=ref.current;
    if(confirmation.open && !dialog.open) dialog.showModal();
    if(!confirmation.open && dialog.open) dialog.close();
    return ()=>{if(dialog.open)dialog.close();};
  },[confirmation.open]);
  return <dialog ref={ref} className="stop-dialog mystery-dialog" aria-labelledby="mystery-confirm-title" aria-describedby="mystery-confirm-description" onCancel={event=>{event.preventDefault();onCancel();}}>
    <span className="eyebrow">SANDBOX FAULT REQUEST</span><h2 id="mystery-confirm-title">Confirm Mystery submission?</h2>
    <p id="mystery-confirm-description">This asks the backend to run the selected sandbox fault under its safety controls. An accepted request does not confirm injection, recovery, or diagnosis.</p>
    <p className="stop-dialog-run">Selection: <strong>{confirmation.label || 'Not available'}</strong></p>
    {!available && <p className="stop-dialog-unavailable">Unavailable: the trial, menu, freshness, or safety controls changed. Cancel and review current state.</p>}
    <div className="stop-dialog-actions"><button autoFocus onClick={onCancel}>Cancel</button><button className="p1-primary" disabled={!available} onClick={onConfirm}>Confirm Mystery request</button></div>
  </dialog>;
}
