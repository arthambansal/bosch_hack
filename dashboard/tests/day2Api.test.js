import { test } from 'node:test';
import assert from 'node:assert/strict';
import { day2Api, mysteryContext } from '../src/api/day2Api.js';
const live = () => ({status:'connected',received:Date.now(),state:{run_status:'running',mystery:{state:'idle',menu:[{id:'M-kill-redis'}]}}});
const json = (body,status=200) => new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
test('Mystery sends exact contracted choice and distinguishes acceptance from outcome',async t=>{
 let calls=0;
 t.mock.method(globalThis,'fetch',async(path,options)=>{calls++; assert.equal(path,'/mystery'); assert.equal(options.method,'POST'); assert.deepEqual(JSON.parse(options.body),{choice_id:'M-kill-redis'}); return json({accepted:true},202);});
 assert.deepEqual(await day2Api.requestMystery('M-kill-redis',live()),{accepted:true}); assert.equal(calls,1);
});
test('Mystery blocks fixture, stale, stopped, missing and non-idle snapshots',async t=>{
 let calls=0;t.mock.method(globalThis,'fetch',()=>{calls++;});
 for(const snapshot of [{...live(),source:'fixture'},{...live(),received:Date.now()-3000},{...live(),status:'disconnected'},{...live(),state:{run_status:'stopped',mystery:{state:'idle'}}},{...live(),state:{mystery:{state:'injected'}}}]) {
  assert.equal(mysteryContext(snapshot),null); await assert.rejects(day2Api.requestMystery('random',snapshot));
 }
 await assert.rejects(day2Api.requestMystery('unknown',live())); await assert.rejects(day2Api.requestMystery('random',live(),{stopRequested:true})); assert.equal(calls,0);
});
test('Mystery 409, 503 and uncertain outcomes never automatically retry',async t=>{
 let calls=0;
 t.mock.method(globalThis,'fetch',async()=>{calls++;return json({error:'already_requested'},409);});
 await assert.rejects(day2Api.requestMystery('random',live()),error=>error.status===409&&!error.uncertain); assert.equal(calls,1);
 t.mock.method(globalThis,'fetch',async()=>{calls++;return json({error:'mystery_busy'},503);});
 await assert.rejects(day2Api.requestMystery('random',live()),error=>error.status===503&&!error.uncertain); assert.equal(calls,2);
 t.mock.method(globalThis,'fetch',async()=>{calls++;throw new Error('network');});
 await assert.rejects(day2Api.requestMystery('random',live()),error=>error.uncertain);assert.equal(calls,3);
 t.mock.method(globalThis,'fetch',async()=>json({accepted:false},202)); await assert.rejects(day2Api.requestMystery('random',live()),error=>error.uncertain);
});
test('History reads exact summaries, Markdown and log lines',async t=>{
 const name='auto_20261010_120000';const rows=[{name,started_at:'2026-10-10T12:00:00',has_report:true}];
 t.mock.method(globalThis,'fetch',async path=>path==='/runs'?json(rows):path.endsWith('/report')?new Response('# Actual report',{headers:{'Content-Type':'text/markdown'}}):json({lines:['exact log']}));
 assert.deepEqual(await day2Api.runs(),rows);assert.equal(await day2Api.report(name),'# Actual report');assert.deepEqual(await day2Api.events(name),{lines:['exact log']});
});
test('History refuses unsafe names before fetching and rejects absent or malformed data',async t=>{
 let calls=0;t.mock.method(globalThis,'fetch',async()=>{calls++;return json({error:'not_found'},404);});
 for(const name of ['..','auto_20261010_120000/..','auto_20261010_120000\\..','%2e%2e']) await assert.rejects(day2Api.report(name));assert.equal(calls,0);
 await assert.rejects(day2Api.events('auto_20261010_120000'),error=>error.status===404);assert.equal(calls,1);
 t.mock.method(globalThis,'fetch',async()=>json({lines:[1]}));await assert.rejects(day2Api.events('auto_20261010_120000'));
 t.mock.method(globalThis,'fetch',async()=>json({not:'a list'}));await assert.rejects(day2Api.runs());
});

test('null Mystery acknowledgement and request timeout remain uncertain; 400 stays rejected',async t=>{
 t.mock.method(globalThis,'fetch',async()=>json(null,202));await assert.rejects(day2Api.requestMystery('random',live()),error=>error.uncertain);
 t.mock.method(globalThis,'fetch',async()=>json({error:'unknown_choice'},400));await assert.rejects(day2Api.requestMystery('random',live()),error=>error.status===400&&!error.uncertain);
 t.mock.method(globalThis,'fetch',async()=>json({error:'timeout'},408));await assert.rejects(day2Api.requestMystery('random',live()),error=>error.uncertain);
});
