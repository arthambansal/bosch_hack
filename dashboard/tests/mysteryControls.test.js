import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

// Hook driver exercises real provider callbacks and shared request refs without
// a DOM. Effects/state are simulated; this is not browser focus/visual coverage.
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
const result=await build({stdin:{contents:`import Provider from './src/components/ControlProvider.jsx';import {begin,commit,reset} from 'react';export {reset};export function render(live){begin();const tree=Provider({live,children:null});commit();return {controls:tree.props.value,stop:tree.props.children[1].props,mystery:tree.props.children[2].props};}`,resolveDir:process.cwd()},bundle:true,write:false,format:'esm',platform:'node',plugins:[{name:'hook-driver',setup(build){build.onResolve({filter:/^react$/},()=>({path:'react',namespace:'driver'}));build.onLoad({filter:/.*/,namespace:'driver'},()=>({contents:hooks,loader:'js'}));}}]});
const driver=await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
const live=()=>({status:'connected',received:Date.now(),refresh:()=>{},state:{run_status:'running',run_dir:'auto_test',mystery:{state:'idle',trial:4,menu:[{id:'M-kill-redis',label:'Crash queue',fault:'kill',target:'redis'}]}}});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const reply=(status,body)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
function setup(t){driver.reset();t.after(()=>driver.reset());let calls=[];t.mock.method(globalThis,'fetch',async(path,options)=>{calls.push({path,options});return reply(202,{accepted:true});});return calls;}

test('Mystery open/cancel sends nothing; explicit confirmation sends once and acknowledges only a request',async t=>{
 const calls=setup(t),snapshot=live();let tree=driver.render(snapshot);assert.equal(tree.controls.mysteryAvailable,true);
 tree.controls.openMysteryDialog('M-kill-redis');tree=driver.render(snapshot);assert.equal(tree.mystery.confirmation.open,true);assert.equal(calls.length,0);
 tree.mystery.onCancel();tree=driver.render(snapshot);assert.equal(tree.mystery.confirmation.open,false);assert.equal(calls.length,0);
 tree.controls.openMysteryDialog('random');tree=driver.render(snapshot);tree.mystery.onConfirm();tree.mystery.onConfirm();await flush();tree=driver.render(snapshot);
 assert.equal(calls.length,1);assert.deepEqual(JSON.parse(calls[0].options.body),{choice_id:'random'});assert.equal(tree.controls.mysteryResult.status,'success');assert.match(tree.controls.mysteryResult.message,/completion remain unconfirmed/);assert.equal(tree.controls.mysteryAvailable,false);
});
test('changing trial/menu, stale snapshots, disconnects, and pending approvals invalidate confirmation',t=>{
 for(const change of [state=>state.state.mystery.trial++,state=>state.state.mystery.menu[0].target='db',state=>state.received=Date.now()-3000,state=>state.status='disconnected',state=>state.state.run_status='stopping',state=>state.state.approval_request={gate_id:'pending'}]) {
  const calls=setup(t),snapshot=live();let tree=driver.render(snapshot);tree.controls.openMysteryDialog('random');tree=driver.render(snapshot);change(snapshot);tree=driver.render(snapshot);assert.equal(tree.mystery.available,false);tree.mystery.onConfirm();assert.equal(calls.length,0);
 }
});
test('STOP invalidates Mystery confirmation and preserves its own explicit confirmation',async t=>{
 const calls=setup(t),snapshot=live();let tree=driver.render(snapshot);tree.controls.openMysteryDialog('random');tree=driver.render(snapshot);tree.controls.openStopDialog();tree=driver.render(snapshot);assert.equal(tree.mystery.confirmation.open,false);assert.equal(tree.stop.open,true);assert.equal(calls.length,0);
 tree.stop.onConfirm();await flush();tree=driver.render(snapshot);assert.equal(calls.length,1);assert.equal(calls[0].path,'/stop');assert.equal(tree.controls.mysteryAvailable,false);
});
test('fixture cannot open a Mystery confirmation or issue a request',t=>{
 const calls=setup(t),snapshot={...live(),source:'fixture'};let tree=driver.render(snapshot);assert.equal(tree.controls.mysteryAvailable,false);tree.controls.openMysteryDialog('random');tree=driver.render(snapshot);assert.equal(tree.mystery.confirmation.open,false);tree.mystery.onConfirm();assert.equal(calls.length,0);
});
test('409 and uncertain network outcomes block same-trial resubmission with no retries',async t=>{
 for(const uncertain of [false,true]) {
  setup(t);let calls=0;t.mock.method(globalThis,'fetch',async()=>{calls++;if(uncertain)throw new Error('network');return reply(409,{error:'already_requested'});});
  const snapshot=live();let tree=driver.render(snapshot);tree.controls.openMysteryDialog('random');tree=driver.render(snapshot);tree.mystery.onConfirm();await flush();tree=driver.render(snapshot);assert.equal(tree.controls.mysteryResult.status,'error');assert.equal(tree.controls.mysteryAvailable,false);tree.controls.openMysteryDialog('random');tree=driver.render(snapshot);tree.mystery.onConfirm();await flush();assert.equal(calls,1);
 }
});
test('400 rejection allows only an explicit revalidated manual attempt and no automatic retry',async t=>{
 setup(t);let calls=0;t.mock.method(globalThis,'fetch',async()=>{calls++;return reply(400,{error:'unknown_choice'});});
 const snapshot=live();let tree=driver.render(snapshot);tree.controls.openMysteryDialog('random');tree=driver.render(snapshot);tree.mystery.onConfirm();await flush();tree=driver.render(snapshot);assert.equal(calls,1);assert.equal(tree.controls.mysteryResult.status,'error');assert.equal(tree.controls.mysteryAvailable,true);tree.controls.openMysteryDialog('random');tree=driver.render(snapshot);assert.equal(calls,1);tree.mystery.onConfirm();await flush();assert.equal(calls,2);
});

test('in-flight Mystery blocks another selection and conflicting approval while STOP remains available',async t=>{
 setup(t);let calls=0,release;t.mock.method(globalThis,'fetch',async()=>{calls++;return new Promise(resolve=>{release=()=>resolve(reply(202,{accepted:true}));});});
 const snapshot=live();let tree=driver.render(snapshot);tree.controls.openMysteryDialog('random');tree=driver.render(snapshot);tree.mystery.onConfirm();tree=driver.render(snapshot);assert.equal(tree.controls.mysteryAvailable,false);assert.equal(tree.controls.stopAvailable,true);
 snapshot.state.agent_active='human';snapshot.state.gate_sync={version:1};snapshot.state.approval_request={gate_id:'gate',created_at:Date.now()/1000-1,expires_at:Date.now()/1000+60};tree=driver.render(snapshot);assert.equal(tree.controls.approvalAvailable,false);tree.controls.approve();assert.equal(calls,1);release();await flush();
});
