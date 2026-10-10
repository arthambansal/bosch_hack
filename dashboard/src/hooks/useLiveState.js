import { useCallback, useEffect, useRef, useState } from 'react';
// Default polling remains 500 ms after each response. Explicit refresh coalesces
// with an in-flight read rather than issuing a concurrent request.
export default function useLiveState() {
 const [live, setLive] = useState({ state: {}, status: 'loading', error: '', received: null });
 const refreshRef = useRef(null);
 const refresh = useCallback(() => refreshRef.current?.(), []);
 useEffect(() => {
  let disposed = false, timer, controller, inFlight = false, queued = false;
  async function poll() {
   if (disposed) return;
   if (inFlight) { queued = true; return; }
   clearTimeout(timer);
   inFlight = true;
   controller = new AbortController();
   const deadline = setTimeout(() => controller.abort(), 4000);
   try {
    const response = await fetch('/state', { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const state = await response.json();
    if (state === null || typeof state !== 'object' || Array.isArray(state)) throw new SyntaxError('Expected a JSON state object');
    if (!disposed) setLive({ state, status: 'connected', received: Date.now(), error: Object.keys(state).length ? '' : 'Connected, but no live state is available yet.' });
   } catch (error) {
    if (!disposed) setLive(previous => ({ ...previous, status: error instanceof SyntaxError ? 'malformed' : 'disconnected', error: `Unable to read /state: ${error.name === 'AbortError' ? 'request timed out' : error.message}. Retrying automatically. ${previous.received ? 'Showing the last received snapshot; telemetry may be stale.' : 'No snapshot received.'}` }));
   } finally {
    clearTimeout(deadline);
    inFlight = false;
    if (!disposed) timer = setTimeout(poll, queued ? 0 : 500);
    queued = false;
   }
  }
  refreshRef.current = () => { if (inFlight) queued = true; else poll(); };
  poll();
  return () => { disposed = true; clearTimeout(timer); controller?.abort(); refreshRef.current = null; };
 }, []);
 return { ...live, refresh };
}
