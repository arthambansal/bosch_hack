import { ControlRequestError } from './controlApi.js';
import { validRunName as validRun } from '../historyModel.js';
export function mysteryContext(live, now = Date.now(), stopRequested = false) {
  const mystery = live?.state?.mystery;
  if (stopRequested || live?.source === 'fixture' || live?.status !== 'connected'
      || !Number.isFinite(live.received) || now < live.received || now - live.received >= 2000
      || ['stopping', 'stopped', 'completed'].includes(live.state.run_status)
      || mystery?.state !== 'idle') return null;
  return mystery;
}
async function responseFor(path, options = {}) {
  let response;
  try { response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', redirect: 'error', ...options }); }
  catch { throw new ControlRequestError(options.method === 'POST' ? 'Mystery request outcome is uncertain. Inspect live state; do not blindly retry.' : 'History request failed.', { uncertain: options.method === 'POST' }); }
  if (!response.ok) {
    let code; try { code = (await response.json()).error; } catch { /* no raw server error text */ }
    throw new ControlRequestError(`Request rejected (HTTP ${response.status}${code ? ': ' + code : ''}).`, { status: response.status, code, uncertain: options.method === 'POST' && (response.status === 408 || response.status >= 500) && code !== 'mystery_busy' });
  }
  return response;
}
async function jsonBody(response) {
  if (!response.headers.get('content-type')?.includes('application/json')) throw new ControlRequestError('Invalid JSON response.');
  return response.json();
}
function runPath(name, type) {
  if (!validRun(name)) throw new ControlRequestError('Invalid run name.');
  return `/runs/${encodeURIComponent(name)}/${type}`;
}
export const day2Api = Object.freeze({
  async requestMystery(choice_id, live, { signal, stopRequested = false } = {}) {
    const context = mysteryContext(live, Date.now(), stopRequested);
    if (!context || typeof choice_id !== 'string' || (choice_id !== 'random' && (!Array.isArray(context.menu) || !context.menu.some(item => item?.id === choice_id)))) throw new ControlRequestError('No fresh, idle Mystery selection is available.');
    const response = await responseFor('/mystery', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({choice_id}), signal });
    let body;
    try { body = await jsonBody(response); } catch { throw new ControlRequestError('Mystery acknowledgement is uncertain.', { uncertain: true }); }
    if (response.status !== 202 || body?.accepted !== true) throw new ControlRequestError('Mystery acknowledgement is uncertain.', { uncertain: true });
    return { accepted: true }; // Accepted request, never an injected fault or completed trial.
  },
  async startMystery(live, { signal } = {}) {
    if (!live || live.source === 'fixture' || live.status !== 'connected') throw new ControlRequestError('Start needs a live connection to the dashboard server.');
    const response = await responseFor('/mystery/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', signal });
    let body;
    try { body = await jsonBody(response); } catch { throw new ControlRequestError('Start acknowledgement is uncertain.', { uncertain: true }); }
    if (body?.started === true) return { started: true, alreadyRunning: false };
    if (body?.already_running === true) return { started: false, alreadyRunning: true };
    throw new ControlRequestError('Start acknowledgement is uncertain.', { uncertain: true });
  },
  async runs({signal} = {}) {
    const body = await jsonBody(await responseFor('/runs', {signal}));
    if (!Array.isArray(body) || body.some(row => !validRun(row?.name) || typeof row.started_at !== 'string' || typeof row.has_report !== 'boolean')) throw new ControlRequestError('Invalid run summaries.');
    return body;
  },
  async report(name, {signal} = {}) {
    const response = await responseFor(runPath(name, 'report'), {signal});
    if (!response.headers.get('content-type')?.includes('text/markdown')) throw new ControlRequestError('Invalid Markdown response.');
    return response.text(); // Untrusted Markdown text; never render as raw HTML.
  },
  async events(name, {signal} = {}) {
    const body = await jsonBody(await responseFor(runPath(name, 'events'), {signal}));
    if (!Array.isArray(body.lines) || body.lines.some(line => typeof line !== 'string')) throw new ControlRequestError('Invalid event lines.');
    return body;
  },
});
