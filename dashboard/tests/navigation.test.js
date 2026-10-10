import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { VIEWS, nextTabIndex, statusPresentation, agentEvents } from '../src/viewModel.js';
import { fmt, pct, localTime } from '../src/data.js';

test('six manual-activation tabs support wrapped arrows, Home and End', () => {
  assert.deepEqual(VIEWS.map(view => view.id), ['overview', 'agents', 'experiments', 'diagnostics', 'recovery', 'history']);
  assert.equal(nextTabIndex(5, 'ArrowRight'), 0);
  assert.equal(nextTabIndex(0, 'ArrowLeft'), 5);
  assert.equal(nextTabIndex(3, 'Home'), 0);
  assert.equal(nextTabIndex(1, 'End'), 5);
  assert.equal(nextTabIndex(1, 'Tab'), null);
  assert.equal(nextTabIndex(1, 'Enter'), null); // native button activation
});

test('global status never shows stale or completed active-agent highlights', () => {
  const live = { status: 'connected', received: 1000, state: { run_status: 'running', phase: 'running', agent_active: 'human', guard: { tripped: false }, experiment: { name: 'Redis crash' } } };
  assert.equal(statusPresentation(live, 1500).agent, 'Approval gate');
  assert.equal(statusPresentation(live, 1500).guard, 'Not tripped');
  assert.equal(statusPresentation(live, 3000).fresh, false);
  assert.equal(statusPresentation(live, 3000).agent, 'Not available');
  assert.equal(statusPresentation({ ...live, status: 'disconnected' }, 1500).agent, 'Not available');
  for (const run_status of ['stopping', 'stopped', 'completed']) {
    const result = statusPresentation({ ...live, state: { ...live.state, run_status } }, 1500);
    assert.equal(result.agent, 'Not available');
    assert.equal(result.experimentCurrent, false);
  }
  assert.equal(statusPresentation({ state: {}, status: 'loading' }).guard, 'Not available');
});

test('missing values are unavailable, measured zero remains zero, events need explicit attribution', () => {
  assert.equal(fmt(null), 'Not available');
  assert.equal(pct(undefined), 'Not available');
  assert.equal(localTime(NaN), 'Not available');
  assert.equal(fmt(0), '0');
  assert.equal(pct(0), '0.0%');
  const events = [{ msg: '[12:00:00] [Diagnostician] E1: quoted cause' }, { msg: '[graph] diagnostician done' }, { msg: 'maybe Diagnostician' }, null];
  assert.deepEqual(agentEvents({ events }, 'Diagnostician'), [events[0]]);
});

// SSR verifies the mounted workspace structure, bindings and accessibility
// relationships. It does not claim pointer/focus or visual browser coverage.
const bundle = await build({ stdin: { contents: `
  import React from 'react';
  import { renderToString } from 'react-dom/server';
  import { DashboardWorkspace } from './src/App.jsx';
  import ControlProvider from './src/components/ControlProvider.jsx';
  import WorkspaceShell from './src/components/WorkspaceShell.jsx';
  import { TERMS } from './src/components/InfoTooltip.jsx';
  export { TERMS };
  export function workspace(live) { return renderToString(React.createElement(ControlProvider, { live }, React.createElement(DashboardWorkspace, { live }))); }
  export function shell(live, view) { return renderToString(React.createElement(ControlProvider, { live }, React.createElement(WorkspaceShell, { live, view, onView: () => {}, onApproval: () => {}, approvalOpen: false }, 'Panel'))); }
`, resolveDir: process.cwd() }, bundle: true, write: false, platform: 'node', format: 'esm', packages: 'external' });
let source = bundle.outputFiles[0].text;
for (const name of ['react', 'react-dom', 'react-dom/server']) source = source.replaceAll(`from "${name}"`, `from ${JSON.stringify(import.meta.resolve(name))}`);
const rendering = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('all views retain global STOP, pending approval access, and selected navigation semantics', () => {
  const now = Date.now();
  const live = { status: 'connected', received: now, state: { run_status: 'running', phase: 'running', run_dir: 'test-run', approval_request: { gate_id: 'test-gate' } } };
  for (const view of VIEWS) {
    const html = rendering.shell(live, view.id);
    assert.match(html, /Emergency stop/);
    assert.match(html, /Approval request/);
    assert.match(html, new RegExp(`id="tab-${view.id}"[^>]*aria-selected="true"`));
    assert.equal((html.match(/role="tab"/g) || []).length, 6);
    assert.doesNotMatch(html, /class="sidebar"/);
  }
});

test('workspace keeps six panels mounted with unique IDs and no fabricated findings or history', () => {
  const html = rendering.workspace({ state: {}, status: 'loading', received: null });
  assert.equal((html.match(/role="tabpanel"/g) || []).length, 6);
  const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(ids).size, ids.length);
  assert.match(html, /Not available/);
  assert.match(html, /run-history endpoints are not implemented/);
  assert.match(html, /not verified Docker measurements/);
  assert.match(html, /Hypothesis · not an observed result/);
  assert.equal((html.match(/id="approval-title"/g) || []).length, 1);
  assert.match(html, /id="experiment-telemetry"/);
  assert.match(html, /id="recovery-controls"/);
  for (const term of ['FMEA', 'RPN', 'gray failure', 'canary', 'guard ticks', 'root cause', 'agent roles']) assert.ok(rendering.TERMS[term]);
});

test('new views use supplied records and escape backend content', () => {
  const html = rendering.workspace({ state: { experiment: { id: 'E6', name: '<script>bad()</script>', reason: 'Backend reason', hypothesis: 'May lose votes' }, queue: [{ id: 'E6', status: 'aborted', root_cause: 'Quoted backend cause' }], fmea_compare: [{ id: 'E6', rpn_before: 100, rpn_after: 20, reduction_pct: 80 }] }, status: 'disconnected', received: null });
  assert.match(html, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>bad/);
  assert.match(html, /Quoted backend cause/);
  assert.match(html, /Backend reason/);
  assert.match(html, /May lose votes/);
});
