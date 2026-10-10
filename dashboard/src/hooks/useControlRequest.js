import { useEffect, useRef, useState } from 'react';

const idle = { status: 'idle', message: '', key: null, action: null };

export default function useControlRequest(scopeKey) {
  const [result, setResult] = useState(idle);
  const mounted = useRef(false);
  const inFlight = useRef(null);
  const settled = useRef(null);
  const currentScope = useRef(scopeKey);
  currentScope.current = scopeKey;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      inFlight.current?.controller.abort();
    };
  }, []);

  async function submit({ key, action, request, successMessage, onError, idempotent = false }) {
    // One approval slot is shared by Approve and Deny; STOP is shared by both
    // buttons. Also block re-submission after acceptance or an uncertain reply.
    if (!key || key !== currentScope.current || inFlight.current
      || (settled.current?.key === key && settled.current.blocked)) return;
    const controller = new AbortController();
    const pending = { key, controller };
    inFlight.current = pending;
    setResult({ key, action, status: 'loading', message: action === 'stop' ? 'Sending STOP request…' : 'Sending approval decision…' });
    const deadline = setTimeout(() => controller.abort(), 10000);
    try {
      await request(controller.signal);
      settled.current = { key, blocked: true };
      if (mounted.current) setResult({ key, action, status: 'success', message: successMessage });
    } catch (error) {
      const uncertain = error?.uncertain === true || error?.name === 'AbortError';
      // A verified idempotent STOP may be manually retried after confirmation;
      // ambiguous approval writes must remain blocked. Never retry automatically.
      settled.current = { key, blocked: uncertain && !idempotent };
      if (mounted.current) setResult({ key, action, status: 'error', message: error?.message || 'The request could not be acknowledged. Inspect live state before retrying.' });
      if (mounted.current) onError?.(error);
    } finally {
      clearTimeout(deadline);
      if (inFlight.current === pending) inFlight.current = null;
    }
  }

  return {
    submit,
    result: result.key === scopeKey ? result : idle,
    blocked: Boolean(inFlight.current) || (result.key === scopeKey
      && (result.status === 'success' || settled.current?.blocked === true)),
  };
}
