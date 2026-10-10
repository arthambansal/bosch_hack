import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// Render once to capture the hook's request coordinator. No browser or network;
// these checks exercise its refs, not UI rendering or effect lifecycle.
const bundle = await build({ stdin: { contents: `
  import React from 'react';
  import { renderToString } from 'react-dom/server';
  import useControlRequest from './src/hooks/useControlRequest.js';
  export function coordinator() {
    let controls;
    function Capture() { controls = useControlRequest('gate'); return null; }
    renderToString(React.createElement(Capture));
    return controls;
  }`, resolveDir: process.cwd() }, bundle: true, write: false, platform: 'node', format: 'esm', packages: 'external' });
// Keep external React imports resolvable from this test file.
const source = bundle.outputFiles[0].text.replaceAll('from "react"', `from ${JSON.stringify(import.meta.resolve('react'))}`)
  .replaceAll('from "react-dom/server"', `from ${JSON.stringify(import.meta.resolve('react-dom/server'))}`);
const { coordinator } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('concurrent and acknowledged duplicate decisions are blocked', async () => {
  const controls = coordinator();
  let calls = 0, release;
  const request = () => { calls++; return new Promise(resolve => { release = resolve; }); };
  const args = { key: 'gate', action: 'approve', request, successMessage: 'Acknowledged' };
  const first = controls.submit(args);
  await controls.submit({ ...args, action: 'deny' });
  assert.equal(calls, 1);
  release(); await first;
  await controls.submit(args);
  assert.equal(calls, 1);
});

test('409 and uncertain outcomes block further same-gate submissions', async () => {
  for (const error of [{ status: 409 }, { uncertain: true }]) {
    const controls = coordinator(); let calls = 0;
    const args = { key: 'gate', action: 'approve', request: async () => { calls++; throw error; } };
    await controls.submit(args); await controls.submit(args);
    assert.equal(calls, 1);
  }
});

test('503 does not retry automatically but permits another deliberate submit', async () => {
  const controls = coordinator(); let calls = 0;
  const args = { key: 'gate', action: 'approve', request: async () => { calls++; throw { status: 503, uncertain: false }; } };
  await controls.submit(args);
  assert.equal(calls, 1);
  await controls.submit(args);
  assert.equal(calls, 2);
  await controls.submit({ ...args, key: 'old-gate' });
  assert.equal(calls, 2);
});
