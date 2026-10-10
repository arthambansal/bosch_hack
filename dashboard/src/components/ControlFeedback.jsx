import React from 'react';
import { Icon } from './ui.jsx';

export default function ControlFeedback({ result }) {
  if (!result || result.status === 'idle') return null;
  return <div className={`control-feedback ${result.status}`} role={result.status === 'error' ? 'alert' : 'status'} aria-live={result.status === 'error' ? 'assertive' : 'polite'} aria-atomic="true">
    <Icon name={result.status === 'success' ? 'check' : result.status === 'loading' ? 'clock' : 'info'} size={15} /><p>{result.message}</p>
  </div>;
}
