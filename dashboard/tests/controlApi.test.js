import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CONTROL_CONTRACTS, createControlApi } from '../src/api/controlApi.js';

// These adapters are test doubles. The opaque body and acknowledgement below
// define no production gate identity, HTTP payload, or response schema.
function fixtureAdapter(overrides = {}) {
  return {
    verified: true,
    getContext: () => ({ key: 'test-scope' }),
    buildRequest: () => ({ body: 'opaque-test-body' }),
    verifyAcknowledgement: async () => true,
    ...overrides,
  };
}

test('production adapters remain unconfigured; all mutations fail before fetch', async t => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls += 1; });
  const api = createControlApi();
  assert.equal(CONTROL_CONTRACTS.approval, null);
  assert.equal(CONTROL_CONTRACTS.stop, null);
  assert.equal(api.getApprovalContext({ approval_request: { id: 'experiment-id' } }), null);
  assert.equal(api.getStopContext({ phase: 'running', run_dir: 'run' }), null);
  for (const method of ['approve', 'deny', 'requestStop']) {
    await assert.rejects(api[method]({ key: 'not-a-verified-gate' }, { confirmed: true }), /unavailable/);
  }
  assert.equal(calls, 0);
});

test('STOP requires explicit confirmation even with a configured test adapter', async t => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls += 1; });
  const api = createControlApi({ stop: fixtureAdapter() });
  await assert.rejects(api.requestStop({ key: 'test-scope' }), /explicit confirmation/);
  assert.equal(calls, 0);
});

test('approve and deny hand booleans to the adapter without guessing a wire body', async t => {
  const decisions = [], calls = [];
  t.mock.method(globalThis, 'fetch', async (...args) => { calls.push(args); return new Response(null, { status: 200 }); });
  const api = createControlApi({ approval: fixtureAdapter({ buildRequest: (context, decision) => {
    decisions.push(decision);
    return { body: 'opaque-test-body' };
  } }) });
  const context = { key: 'test-scope' };
  await api.approve(context);
  await api.deny(context);
  assert.deepEqual(decisions, [true, false]);
  assert.equal(calls.length, 2);
  for (const [path, options] of calls) {
    assert.equal(path, '/approve');
    assert.equal(options.method, 'POST');
    assert.equal(options.body, 'opaque-test-body');
    assert.equal(options.redirect, 'error');
  }
});

test('HTTP 2xx alone cannot be presented as success', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>fallback</html>', { status: 200 }));
  const api = createControlApi({ approval: fixtureAdapter({ verifyAcknowledgement: async () => false }) });
  await assert.rejects(api.approve({ key: 'test-scope' }), error => error.uncertain === true && /did not verify/.test(error.message));
});

test('missing endpoints and stale submissions surface HTTP errors without retrying', async t => {
  let status = 501, calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls += 1; return new Response(null, { status }); });
  const api = createControlApi({ approval: fixtureAdapter() });
  await assert.rejects(api.approve({ key: 'test-scope' }), error => error.status === 501);
  status = 409;
  await assert.rejects(api.deny({ key: 'test-scope' }), error => error.status === 409);
  assert.equal(calls, 2);
});

test('lost acknowledgement is an uncertain outcome, not an automatic retry', async t => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls += 1; throw new Error('connection lost'); });
  const api = createControlApi({ stop: fixtureAdapter() });
  await assert.rejects(api.requestStop({ key: 'test-scope' }, { confirmed: true }), error => error.uncertain === true);
  assert.equal(calls, 1);
});

test('server failure can have an uncertain outcome and must not invite a blind retry', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 500 }));
  const api = createControlApi({ stop: fixtureAdapter() });
  await assert.rejects(api.requestStop({ key: 'test-scope' }, { confirmed: true }), error => error.status === 500 && error.uncertain === true);
});
