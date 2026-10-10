import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// Drive the real provider with explicit poll and heartbeat times. State/effect
// scheduling is simulated; browser verification covers the visible strip.
const hooks = `
let slots=[],cursor=0,effects=[];
export function reset(){for(const slot of slots)slot?.cleanup?.();slots=[];effects=[];cursor=0;}
export function begin(){cursor=0;effects=[];}
export function commit(){for(const run of effects)run();effects=[];}
export function useState(initial){const i=cursor++;if(!slots[i])slots[i]={value:typeof initial==='function'?initial():initial};return [slots[i].value,value=>{slots[i].value=typeof value==='function'?value(slots[i].value):value;}];}
export function useRef(initial){const i=cursor++;if(!slots[i])slots[i]={current:initial};return slots[i];}
export function useEffect(effect,deps){const i=cursor++,old=slots[i];if(!old||deps.some((value,index)=>value!==old.deps[index]))effects.push(()=>{old?.cleanup?.();slots[i]={deps,cleanup:effect()};});}
export const createContext=()=>({Provider:'provider'});
export const useContext=()=>null;
export default {createElement:(type,props,...children)=>({type,props:{...props,children}})};
`;
const result = await build({ stdin: { contents: `
  import Provider from './src/components/ControlProvider.jsx';
  import { statusPresentation } from './src/viewModel.js';
  import { begin, commit, reset } from 'react';
  export { reset };
  export function render(live) {
    begin(); const tree=Provider({live,children:null}); commit();
    const controls=tree.props.value;
    return {controls,status:statusPresentation(live,controls.now)};
  }`, resolveDir: process.cwd() }, bundle: true, write: false, format: 'esm', platform: 'node', plugins: [{ name: 'hook-driver', setup(build) {
    build.onResolve({filter:/^react$/},()=>({path:'react',namespace:'driver'}));
    build.onLoad({filter:/.*/,namespace:'driver'},()=>({contents:hooks,loader:'js'}));
  }}] });
const driver = await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);

function setup(t) {
  driver.reset(); let now=10000, heartbeat, intervals=0;
  t.mock.method(Date,'now',()=>now);
  t.mock.method(globalThis,'setInterval',(callback,delay)=>{assert.equal(delay,500);intervals++;heartbeat=callback;return 1;});
  t.mock.method(globalThis,'clearInterval',()=>{});
  t.mock.method(globalThis,'fetch',()=>{assert.fail('Freshness revalidation must not submit controls or start polling');});
  t.after(()=>driver.reset());
  return {at(value){now=value;},tick(){heartbeat();},intervals:()=>intervals};
}
function live(received=10000) {
  return {status:'connected',received,state:{run_status:'running',phase:'running',run_dir:'test-run',agent_active:'human',gate_sync:{version:1},approval_request:{gate_id:'gate',created_at:9,expires_at:30}}};
}
function expectFresh(snapshot, expected) {
  const {controls,status}=driver.render(snapshot);
  assert.equal(status.fresh,expected);
  assert.equal(controls.approvalAvailable,expected);
  assert.equal(controls.stopAvailable,expected);
  return controls;
}

test('polls between heartbeat ticks stay fresh and approval availability remains stable',t=>{
  const clock=setup(t),snapshot=live();expectFresh(snapshot,true);
  for(const received of [10100,10600,11100,11600]) {
    clock.at(received);snapshot.received=received;
    assert.equal(expectFresh(snapshot,true).now,received);
    clock.at(received+400);clock.tick();expectFresh(snapshot,true);
  }
  assert.equal(clock.intervals(),1); // No timer recreation or extra heartbeat.
});
test('freshness expires at two seconds and reconnecting receipt restores availability',t=>{
  const clock=setup(t),snapshot=live();expectFresh(snapshot,true);
  clock.at(11999);clock.tick();expectFresh(snapshot,true);
  clock.at(12000);clock.tick();expectFresh(snapshot,false);
  clock.at(12500);clock.tick();expectFresh(snapshot,false);
  snapshot.received=12500;expectFresh(snapshot,true);
});
test('future and invalid receipt timestamps fail closed for strip, approval and STOP',t=>{
  setup(t);
  for(const received of [10001,20000,Infinity,NaN,null,'10000'])expectFresh(live(received),false);
});
test('expired or future-created gates remain unavailable with a fresh response',t=>{
  const clock=setup(t),snapshot=live();snapshot.state.approval_request.expires_at=10.1;
  expectFresh(snapshot,true);clock.at(10100);snapshot.received=10100;
  let result=driver.render(snapshot);assert.equal(result.status.fresh,true);assert.equal(result.controls.approvalAvailable,false);assert.equal(result.controls.stopAvailable,true);
  snapshot.state.approval_request={gate_id:'future',created_at:11,expires_at:30};
  result=driver.render(snapshot);assert.equal(result.controls.approvalAvailable,false);
});
test('disconnected and malformed connections stay stale across heartbeats and retain control guards',t=>{
  const clock=setup(t),snapshot=live();expectFresh(snapshot,true);
  for(const status of ['disconnected','malformed','loading']) {
    snapshot.status=status;expectFresh(snapshot,false);clock.at(10500);clock.tick();expectFresh(snapshot,false);
  }
});
test('fixture stays static with live-looking approval and Mystery state; Mystery still rejects stale and future receipts',t=>{
  const clock=setup(t),snapshot=live();snapshot.source='fixture';
  snapshot.state.mystery={state:'idle',trial:1,menu:[{id:'M-kill-redis',label:'Crash queue',fault:'kill',target:'redis'}]};
  assert.equal(expectFresh(snapshot,false).mysteryAvailable,false);
  clock.at(10500);clock.tick();snapshot.received=10500;
  assert.equal(expectFresh(snapshot,false).mysteryAvailable,false);
  delete snapshot.source;delete snapshot.state.approval_request;
  assert.equal(driver.render(snapshot).controls.mysteryAvailable,true);
  snapshot.received=10501;assert.equal(driver.render(snapshot).controls.mysteryAvailable,false);
  snapshot.received=8500;assert.equal(driver.render(snapshot).controls.mysteryAvailable,false);
});
