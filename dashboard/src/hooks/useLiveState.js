import { useEffect, useState } from 'react';
// Schedule only after a response; abort in-flight work and timers on unmount.
export default function useLiveState() {
 const [live, setLive] = useState({ state: {}, status: 'loading', error: '', received: null });
 useEffect(() => {
  let disposed = false, timer, controller;
  async function poll() {
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
    if (!disposed) timer = setTimeout(poll, 500);
   }
  }
  poll();
  return () => { disposed = true; clearTimeout(timer); controller?.abort(); };
 }, []);
 return live;
}
