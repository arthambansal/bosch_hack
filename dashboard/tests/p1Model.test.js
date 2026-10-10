import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mysteryPresentation, mysteryIdentity, mysterySubmissionContext, mysteryConfirmationValid, memoryPresentation, fixesPresentation, planPresentation, predictionPresentation, impactPresentation } from '../src/p1Model.js';
const live=()=>({status:'connected',received:Date.now(),state:{run_status:'running',run_dir:'auto_test',mystery:{state:'idle',trial:4,menu:[{id:'M-kill-redis',label:'Crash queue',fault:'kill',target:'redis'}]}}});
test('absent and partial P1 measurements stay unavailable, while measured zero survives',()=>{
 assert.equal(memoryPresentation(undefined).status,'Not available');assert.equal(memoryPresentation({last_hit:null}).status,'No memory hit reported');assert.equal(memoryPresentation({last_hit:{similarity:0,saved_s:0}}).similarity,'0.0%');
 assert.equal(memoryPresentation({last_hit:{similarity:0,saved_s:0}}).saved,'0 s');assert.equal(memoryPresentation({last_hit:{similarity:false}}).similarity,'Not available');
 assert.deepEqual(fixesPresentation(null),[]);assert.deepEqual(planPresentation(null).candidates,[]);assert.equal(planPresentation({}).reason,'Not available');
 const impact=impactPresentation(null);for(const key of ['lost','accepted','outage','failed'])assert.equal(impact[key],'Not available');
 assert.equal(impactPresentation({votes_lost:0,outage_s:0,failed_requests_pct:42}).lost,'0');assert.equal(impactPresentation({failed_requests_pct:42}).failed,'42%');
 assert.equal(predictionPresentation({items:[{}]}).right,'Not available');assert.equal(predictionPresentation({items:[{}]}).items[0].correct,'Not available');
});
test('memory displays only the reported match, similarity and measured saved time',()=>{
 const memory=memoryPresentation({signatures:6,last_hit:{experiment:'E4',signature_id:'S-match',similarity:0.92,seen_in_run:'auto_previous',root_cause:'Observed cause',saved_s:88.5}});
 assert.equal(memory.status,'Reported memory hit');assert.equal(memory.similarity,'92.0%');assert.equal(memory.saved,'88.5 s');assert.equal(memory.run,'auto_previous');assert.equal(memory.signature,'S-match');assert.equal('confidence' in memory,false);
});
test('fix statuses and contracted RPN are preserved; code suggestions never become verified',()=>{
 for(const status of ['proposed','applied','verified','not_improved','rolled_back']) assert.equal(fixesPresentation([{kind:'compose',status}])[0].status,status);
 const fix=fixesPresentation([{kind:'compose',status:'verified',rpn:[{id:'E2',before:270,after:30},{id:'E3',before:null}]}])[0];
 assert.deepEqual(fix.rpn,[{id:'E2',before:'270',after:'30'},{id:'E3',before:'Not available',after:'Not available'}]);
 const suggestion=fixesPresentation([{kind:'code_suggestion',status:'verified',diff:'read only'}])[0];assert.equal(suggestion.status,'Not available');assert.equal(suggestion.inconsistent,true);
});
test('ranking preserves published order and selection without reconstructing partial rankings',()=>{
 const plan=planPresentation({chosen:'pause:db',reason:'Backend reason',candidates:[{id:'kill:db',risk_score:9},{id:'pause:db',risk_score:8}]});
 assert.equal(plan.reason,'Backend reason');assert.deepEqual(plan.candidates.map(item=>item.id),['kill:db','pause:db']);assert.equal(plan.candidates[1].selected,true);assert.equal(plan.invalid,false);
 const invalid=planPresentation({candidates:[{id:'first',risk_score:1},{id:'second',risk_score:9}]});assert.equal(invalid.invalid,true);assert.equal(invalid.candidates[0].id,'first');
});
test('prediction checks mean agreement, and correctness/counters are never recomputed',()=>{
 const result=predictionPresentation({right:4,total:6,items:[{id:'E1',predicted:{data_loss:true,recovers:false,probes_affected:['vote_write']},check:{data_loss:false,recovers:true},correct:true}]});
 assert.equal(result.right,'4');assert.equal(result.total,'6');assert.equal(result.items[0].correct,'Correct');assert.equal(result.items[0].rows[2].prediction,'Yes');assert.equal(result.items[0].rows[2].check,'Does not match');assert.equal(result.items[0].rows[1].prediction,'No');assert.equal(result.items[0].rows[1].check,'Matches prediction');assert.equal(result.items[0].rows[0].check,'Not available');
});
test('unrevealed answer and correctness are stripped, even if backend mistakenly supplies them',()=>{
 for(const state of ['off','idle','injected','detected','diagnosed','unknown',undefined]) {
  const result=mysteryPresentation({state,answer:{fault:'SECRET'},correct:{top1:true},guess:{fault:'guess'}});
  assert.equal(result.answer,null);assert.equal(result.correct,null);if(state!=='diagnosed')assert.equal(result.guess,null);
 }
 const reveal=mysteryPresentation({state:'revealed',answer:{fault:'pause',target:'db'},correct:{top1:true},accuracy:{trials:3,top1:2}});
 assert.equal(reveal.answer.fault,'pause');assert.equal(reveal.correct.top1,'Yes');assert.equal(reveal.correct.top3,'Not available');assert.equal(reveal.accuracy.trials,'3');assert.equal(reveal.accuracy.top1,'2');assert.equal(reveal.accuracy.target,'Not available');
});
test('Mystery requires fresh live idle identity, valid menu and no conflicting action',()=>{
 const snapshot=live();assert.ok(mysterySubmissionContext(snapshot));
 for(const input of [{...snapshot,source:'fixture'},{...snapshot,status:'disconnected'},{...snapshot,received:Date.now()-3000},{...snapshot,received:Date.now()+5000},{...snapshot,state:{...snapshot.state,run_status:'stopping'}},{...snapshot,state:{...snapshot.state,approval_request:{gate_id:'pending'}}},{...snapshot,state:{...snapshot.state,mystery:{...snapshot.state.mystery,state:'injected'}}},{...snapshot,state:{...snapshot.state,run_dir:null}},{...snapshot,state:{...snapshot.state,mystery:{state:'idle',menu:[]}}}]) assert.equal(mysterySubmissionContext(input),null);
 for(const conflict of [{pending:true},{dialogOpen:true},{stopRequested:true}]) assert.equal(mysterySubmissionContext(snapshot,conflict),null);
 assert.equal(mysteryIdentity({mystery:{trial:1}}),null);
});
test('confirmation is bound to the same trial/menu and explicit choice, including random',()=>{
 const snapshot=live(),context=mysterySubmissionContext(snapshot);const confirmation={open:true,signature:context.signature,choice:'M-kill-redis'};
 assert.ok(mysteryConfirmationValid(confirmation,context));assert.ok(mysteryConfirmationValid({...confirmation,choice:'random'},context));
 assert.equal(mysteryConfirmationValid({...confirmation,open:false},context),false);assert.equal(mysteryConfirmationValid({...confirmation,choice:'unknown'},context),false);
 snapshot.state.mystery.trial++;assert.equal(mysteryConfirmationValid(confirmation,mysterySubmissionContext(snapshot)),false);snapshot.state.mystery.trial--;
 snapshot.state.mystery.menu[0].target='db';assert.equal(mysteryConfirmationValid(confirmation,mysterySubmissionContext(snapshot)),false);
 assert.equal(mysteryConfirmationValid(confirmation,null),false);
});
