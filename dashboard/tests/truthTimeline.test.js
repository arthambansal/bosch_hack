import { test } from 'node:test';
import assert from 'node:assert/strict';
import { truthPresentation, timestamp } from '../src/truthModel.js';
import { timelineEvidence } from '../src/timelineModel.js';
import { fixtureSelection, loadFixture, FIXTURE_NAMES } from '../src/fixtures.js';
import { liveApprovalContext } from '../src/api/controlApi.js';
import { statusPresentation } from '../src/viewModel.js';
test('missing and partial truth never infer health or zero', () => {
  for (const input of [undefined,null,{}, {canaries:{sent:null,stored:false}}]) {
    const result=truthPresentation(input); assert.equal(result.status,null); assert.equal(result.monitoring,null);
    assert.equal(result.canaries.sent,'Not available'); assert.equal(result.canaries.stored,'Not available');
  }
  const result=truthPresentation({status:'ok',canaries:{sent:0}});
  assert.equal(result.status,'ok'); assert.equal(result.monitoring,null); assert.equal(result.canaries.sent,0); assert.equal(result.canaries.pending,'Not available');
  assert.equal(timestamp(null),'Not available'); assert.equal(timestamp(Infinity),'Not available');
});
test('all authoritative states and exact failing invariant booleans',()=>{
  for(const status of ['ok','diverged','down','unknown']) assert.equal(truthPresentation({status}).status,status);
  for(const monitoring of ['healthy','degraded','unknown']) assert.equal(truthPresentation({monitoring}).monitoring,monitoring);
  const result=truthPresentation({status:'diverged',monitoring:'healthy',diverged_at:100,invariants:[{name:'votes',ok:false,detail:'2 missing'},{ok:true},{ok:null},{ok:0},{ok:'false'}]});
  assert.deepEqual(result.invariants.map(x=>x.status),['Failing','Passed','Not available','Not available','Not available']);
  assert.equal(result.invariants[0].detail,'2 missing'); assert.notEqual(result.divergedAt,'Not available'); assert.equal(result.inconsistent,false);
  assert.equal(truthPresentation({status:'diverged',monitoring:'degraded'}).inconsistent,true);
});
test('timeline markers require explicit timestamped events, never predictions or restore commands',()=>{
  const events=[{t:4,kind:'ok',msg:'[12:00:00] Recovered in 0.4s'},{t:1,kind:'inject',msg:'INJECT KILL -> redis OK'},{t:2,kind:'guard',msg:'guard 1/3: high latency'},{t:3,kind:'guard',msg:'!!!! KILL SWITCH: high latency !!!!'}];
  const markers=timelineEvidence(events); assert.deepEqual(markers.map(x=>x.stage),['Fault injection','Detection','Kill switch','Probe recovery']); assert.equal(markers[3].msg,events[0].msg); assert.equal(markers[3].t,4);
  assert.equal(timelineEvidence([{kind:'inject',msg:'INJECT kill OK'},{t:1,kind:'ai',msg:'Recovered in 1s'},{t:2,kind:'restore',msg:'RESTORE kill OK'},{t:3,kind:'warn',msg:'NOT recovered within timeout'},{t:4,kind:'warn',msg:'INJECT kill FAILED'},{t:5,kind:'ai',msg:'predicts KILL SWITCH: soon'}]).length,0);
  assert.deepEqual(timelineEvidence(undefined),[]); assert.deepEqual(timelineEvidence({guard:{tripped:true,elapsed:10},phase:'healed'}),[]);
});
test('fixture allowlist fails closed without path traversal or live fallback',async()=>{
  assert.equal(fixtureSelection(''),null);
  for(const query of ['?fixture=','?fixture=../../runs/live_state','?fixture=gray_failure&fixture=idle','?fixture=toString']) {
    const selection=fixtureSelection(query); assert.equal(selection.valid,false); await assert.rejects(loadFixture(selection),/Unknown fixture/);
  }
  for(const name of FIXTURE_NAMES) assert.equal(fixtureSelection('?fixture='+name).valid,true);
});
test('fixture cannot obtain fresh status or approval with a live-looking gate',()=>{
  const now=Date.now(),live={status:'connected',received:now,state:{run_status:'running',agent_active:'human',gate_sync:{version:1},approval_request:{gate_id:'exact',created_at:now/1000-1,expires_at:now/1000+60}}};
  assert.ok(liveApprovalContext(live,false,now)); assert.equal(liveApprovalContext({...live,source:'fixture'},false,now),null); assert.equal(statusPresentation({...live,source:'fixture'},now).fresh,false);
});
