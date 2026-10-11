import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { preserveSelection, replayIndex, recordedTime, regressionRows } from '../src/historyModel.js';
import { day2Api } from '../src/api/day2Api.js';

test('server order and existing selection are preserved; empty listing clears selection',()=>{
  const rows=[{name:'new'},{name:'old'}];assert.equal(preserveSelection(rows,'old'),'old');assert.equal(preserveSelection(rows,'missing'),'new');assert.equal(preserveSelection([],'old'),'');
});
test('deterministic replay clamps steps and reset, timestamps require valid recorded clock',()=>{
  assert.equal(replayIndex(0,'back',4),0);assert.equal(replayIndex(1,'next',4),2);assert.equal(replayIndex(3,'next',4),3);assert.equal(replayIndex(3,'reset',4),0);assert.equal(replayIndex(0,'next',0),-1);
  assert.equal(recordedTime('INFO     [23:59:59] message'),'23:59:59');for(const line of ['[25:10:00] bad','text [10:00:00]','no timestamp'])assert.equal(recordedTime(line),null);
});
test('regression missing, partial, never run, pass and fail do not fabricate success',()=>{
  assert.equal(regressionRows(undefined),null);assert.deepEqual(regressionRows([]),[]);assert.equal(regressionRows([null])[0].status,'Not available');assert.equal(regressionRows([{last_status:'never_run'}])[0].at,'Not available');assert.equal(regressionRows([{last_status:'pass'}])[0].status,'Passed last replay');assert.equal(regressionRows([{last_status:'fail',last_run_at:0}])[0].at,'1970-01-01T00:00:00.000Z');
});
test('History GETs validate names and malformed events, preserve lines and avoid mutation endpoints',async t=>{
  const calls=[];let body={lines:['INFO [10:00:00] first','','bad time']};t.mock.method(globalThis,'fetch',async(path,options)=>{calls.push([path,options.method]);return new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json'}});});
  const name='auto_20261010_141752';assert.deepEqual((await day2Api.events(name)).lines,body.lines);for(const invalid of ['../main','auto_20261010_141752/stop','https://bad',name+'\n'])await assert.rejects(day2Api.events(invalid));
  body={lines:[null]};await assert.rejects(day2Api.events(name));body={};await assert.rejects(day2Api.events(name));assert.ok(calls.every(([path,method])=>path.startsWith('/runs/') && !method));
});
test('report response type is validated; missing report and transport failure remain distinct',async t=>{
  t.mock.method(globalThis,'fetch',async()=>new Response('<html>bad</html>',{headers:{'Content-Type':'text/html'}}));await assert.rejects(day2Api.report('auto_20261010_141752'),/Invalid Markdown/);
  t.mock.method(globalThis,'fetch',async()=>new Response('{}',{status:404,headers:{'Content-Type':'application/json'}}));await assert.rejects(day2Api.report('auto_20261010_141752'),error=>error.status===404);
  t.mock.method(globalThis,'fetch',async()=>{throw Error();});await assert.rejects(day2Api.report('auto_20261010_141752'),error=>error.status===null);
});

const bundle=await build({stdin:{contents:`import React from 'react';import {renderToString} from 'react-dom/server';import {RecordedReplay,ReportViewer} from './src/components/HistoryPanel.jsx';import RegressionPanel from './src/components/RegressionPanel.jsx';export function replay(lines){return renderToString(React.createElement(RecordedReplay,{lines,active:true}));}export function report(report){return renderToString(React.createElement(ReportViewer,{report}));}export function regression(value){return renderToString(React.createElement(RegressionPanel,{value}));}`,resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external'});
let source=bundle.outputFiles[0].text;for(const name of ['react','react-dom','react-dom/server'])source=source.replaceAll(`from "${name}"`,`from ${JSON.stringify(import.meta.resolve(name))}`);
const render=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
test('reports remain escaped original Markdown, empty files are distinguished',()=>{
  const html=render.report('# Heading\n| column |\n<script>alert(1)</script>\n<img onerror=bad>');assert.match(html,/# Heading/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>|<img/);assert.match(html,/Copy report/);assert.match(render.report('  '),/Report file is empty/);
});
test('large replay renders bounded window in original order; empty logs and unknown timestamps are readable',()=>{
  assert.match(render.replay([]),/No recorded events/);const html=render.replay(Array.from({length:10000},(_,i)=>`original ${i}`));assert.equal((html.match(/aria-current="step"/g)||[]).length,1);assert.match(html,/original 0/);assert.match(html,/original 40/);assert.doesNotMatch(html,/original 41/);assert.match(html,/Timestamp not available/);assert.match(render.regression(undefined),/Not available/);
});
