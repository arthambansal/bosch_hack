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
  export { loadFixture } from './src/fixtures.js';
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
  assert.match(html, /Open History to load recorded runs/);
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

test('fixture source stays labelled and STOP stays disabled with live-looking state',()=>{
 const html=rendering.workspace({source:'fixture',fixtureName:'gray_failure',status:'connected',received:Date.now(),state:{run_status:'running',run_dir:'fixture-run',truth:{status:'diverged',monitoring:'healthy',invariants:[{name:'delivery',ok:false,detail:'three missing'}]},events:[{t:100,kind:'ok',msg:'Recovered in 0.4s'}]}});
 assert.match(html,/FIXTURE DATA/); assert.match(html,/mutations and live polling disabled/); assert.match(html,/GRAY FAILURE/); assert.match(html,/three missing/); assert.match(html,/Recovered in 0.4s/); assert.doesNotMatch(html,/Backend connected/);
 assert.match(html,/<button[^>]*disabled=""[^>]*aria-describedby="stop-note"/);
});

test('every permitted fixture loads locally without fetch and returns isolated snapshots', async t => {
  t.mock.method(globalThis, 'fetch', () => { throw new Error('Fixture mode must not poll or mutate'); });
  for (const name of ['approval_pending','completed_with_fixes','gray_failure','idle','mystery_revealed']) {
    const state = await rendering.loadFixture({name,valid:true});
    assert.ok(state.truth); state.truth.status = 'modified-test-copy';
    const fresh = await rendering.loadFixture({name,valid:true});
    assert.notEqual(fresh.truth.status,'modified-test-copy');
  }
});

test('P1 fixture panels use published counters, read-only fixes, and safe reveal boundaries',async()=>{
 const state=await rendering.loadFixture({name:'completed_with_fixes',valid:true});
 const html=rendering.workspace({state,source:'fixture',fixtureName:'completed_with_fixes',status:'fixture',received:null});
 for(const text of ['Failure memory','92.0%','88.5 s','rolled_back','270','30','Read-only proposed diff']) assert.ok(html.includes(text),text);
 assert.match(html,/Similarity/);assert.match(html,/Backend right counter/);assert.match(html,/Backend total counter/);assert.match(html,/42%/);assert.match(html,/Break it yourself/);assert.match(html,/<button[^>]*disabled=""[^>]*>Break it yourself/);
 assert.doesNotMatch(html,/<button[^>]*>Apply patch/);
 const secret={state:'diagnosed',trial:4,answer:{fault:'HIDDEN_ANSWER',target:'HIDDEN_TARGET'},correct:{top1:true},guess:{fault:'pause',target:'db',root_cause:'Published guess'}};
 const hidden=rendering.workspace({state:{mystery:secret},status:'disconnected',received:null});assert.doesNotMatch(hidden,/HIDDEN_ANSWER|HIDDEN_TARGET/);assert.match(hidden,/Published guess/);
 const revealed=rendering.workspace({state:{mystery:{...secret,state:'revealed'}},status:'disconnected',received:null});assert.match(revealed,/HIDDEN_ANSWER/);
});
test('fresh idle Mystery exposes selectable menu but pending approval disables submission',()=>{
 const now=Date.now();const state={run_dir:'test-run',run_status:'running',mystery:{state:'idle',trial:1,menu:[{id:'M-kill-redis',fault:'kill',target:'redis',label:'Published Redis fault'}]}};
 const html=rendering.workspace({state,status:'connected',received:now});assert.match(html,/<select id="mystery-choice">/);assert.match(html,/Published Redis fault/);
 const blocked=rendering.workspace({state:{...state,approval_request:{gate_id:'gate'}},status:'connected',received:now});assert.match(blocked,/<select id="mystery-choice" disabled=""/);
 const fixture=rendering.workspace({state,status:'connected',received:now,source:'fixture'});assert.match(fixture,/<select id="mystery-choice" disabled=""/);
});


test('Diagnostics references Recovery once while critical rollback and untested evidence remain visible', () => {
 const html=rendering.workspace({source:'fixture',status:'fixture',state:{fixes:[{id:'F1',status:'applied',rollback_failed:true,untested:['E5']}],events:[]}});
 const diagnostics=html.split('id="view-diagnostics"')[1].split('id="view-recovery"')[0];
 assert.match(diagnostics,/View recovery evidence/);
 assert.match(diagnostics,/rollback failure records/);
 assert.match(diagnostics,/experiments not re-tested/);
 assert.doesNotMatch(diagnostics,/REPORTED REMEDIATION/);
 assert.equal((html.match(/REPORTED REMEDIATION/g)||[]).length,1);
 for(const term of ['p95 latency','MTTD','MTTR','Governor','Provenance','Confidence','Similarity','Rollback','Regression','blast radius','verification status','Untested fixes'])assert.ok(rendering.TERMS[term],term);
});
