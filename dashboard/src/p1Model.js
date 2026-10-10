import { obj, arr, num, fmt, pct } from './data.js';
import { textValue } from './viewModel.js';
import { mysteryContext } from './api/day2Api.js';
export const boolText = value => value === true ? 'Yes' : value === false ? 'No' : 'Not available';
const strings = value => Array.isArray(value) && value.every(item => typeof item === 'string') ? value.length ? value.join(', ') : 'None reported' : 'Not available';
const faults = ['kill','pause','partition','latency','spike'];
export function mysteryPresentation(value) {
  const raw = obj(value), guess = obj(raw.guess), reveal = raw.state === 'revealed';
  const showGuess = ['diagnosed','revealed'].includes(raw.state) && Object.keys(guess).length > 0;
  return {
    state: ['off','idle','injected','detected','diagnosed','revealed'].includes(raw.state) ? raw.state : 'Not available',
    trial: fmt(raw.trial), chosenBy: textValue(raw.chosen_by),
    menu: arr(raw.menu).filter(item => typeof obj(item).id === 'string' && item.id.trim() && faults.includes(item.fault) && typeof item.target === 'string' && item.target.trim()).map(item => ({id:item.id,label:textValue(item.label),fault:item.fault,target:item.target})),
    guess: showGuess ? {fault:textValue(guess.fault),target:textValue(guess.target),confidence: num(guess.confidence) && guess.confidence >= 0 && guess.confidence <= 1 ? pct(guess.confidence) : 'Not available',rootCause:textValue(guess.root_cause),evidence:arr(guess.evidence).filter(item=>typeof item==='string'),top3:arr(guess.top3).map(item=>({fault:textValue(obj(item).fault),target:textValue(obj(item).target),confidence: num(obj(item).confidence) && item.confidence >= 0 && item.confidence <= 1 ? pct(item.confidence) : 'Not available'})),memoryHit:boolText(guess.memory_hit)} : null,
    answer: reveal ? {fault:textValue(obj(raw.answer).fault),target:textValue(obj(raw.answer).target)} : null,
    correct: reveal ? Object.fromEntries(['top1','top3','target'].map(key=>[key,boolText(obj(raw.correct)[key])])) : null,
    accuracy: Object.fromEntries(['trials','top1','top3','target'].map(key=>[key,fmt(obj(raw.accuracy)[key])])),
    injectedAt:raw.injected_at,detectedAt:raw.detected_at,diagnosedAt:raw.diagnosed_at,detectedBy:textValue(raw.detected_by),
  };
}
// This is only a client-side duplicate scope, never a backend authorization token.
export function mysteryIdentity(state) {
  const mystery=obj(state.mystery);
  return typeof state.run_dir === 'string' && state.run_dir && Number.isInteger(mystery.trial) && mystery.trial >= 0
    ? JSON.stringify([state.run_dir,mystery.trial]) : null;
}
export function mysterySubmissionContext(live, conflicts = {}, now = Date.now()) {
  const raw=mysteryContext(live,now,conflicts.stopRequested),key=mysteryIdentity(obj(live?.state));
  if (!raw || !key || conflicts.pending || conflicts.dialogOpen || live.state.approval_request || live.state.run_status !== 'running') return null;
  const menu=mysteryPresentation(raw).menu;
  if (!menu.length || new Set(menu.map(item=>item.id)).size !== menu.length) return null;
  return {key,menu,signature:JSON.stringify([key,menu])};
}
export function mysteryConfirmationValid(confirmation, context) {
  return Boolean(confirmation?.open && context && confirmation.signature === context.signature
    && (confirmation.choice === 'random' || context.menu.some(item=>item.id===confirmation.choice)));
}
export function memoryPresentation(value) {
  const raw=obj(value),hit=obj(raw.last_hit),hasHit=Object.keys(hit).length>0;
  return {status:hasHit?'Reported memory hit':raw.last_hit===null?'No memory hit reported':'Not available',signatures:fmt(raw.signatures),experiment:textValue(hit.experiment),signature:textValue(hit.signature_id),run:textValue(hit.seen_in_run),rootCause:textValue(hit.root_cause),similarity:num(hit.similarity)&&hit.similarity>=0&&hit.similarity<=1?pct(hit.similarity):'Not available',saved:fmt(hit.saved_s,' s')};
}
export function fixesPresentation(value) {
  return arr(value).map(raw=>{
    const fix=obj(raw),suggestion=fix.kind==='code_suggestion';
    const validStatus=['proposed','applied','verified','not_improved','rolled_back'].includes(fix.status);
    return {id:textValue(fix.id),title:textValue(fix.title),kind:['compose','code_suggestion'].includes(fix.kind)?fix.kind:'Not available',status: validStatus && (!suggestion || fix.status==='proposed')?fix.status:'Not available',inconsistent:suggestion&&fix.status!=='proposed',reason:textValue(fix.why),for:strings(fix.for),diff:textValue(fix.diff),rpn:arr(fix.rpn).map(row=>({id:textValue(obj(row).id),before:fmt(obj(row).before),after:fmt(obj(row).after)}))};
  });
}
export function planPresentation(value) {
  const raw=obj(value),candidates=arr(raw.candidates);
  return {turn:fmt(raw.turn),chosen:textValue(raw.chosen),reason:textValue(raw.reason),covered:strings(raw.types_covered),required:fmt(raw.types_required),invalid: candidates.length>10 || candidates.some((row,index)=>!num(obj(row).risk_score)||(index>0&&obj(candidates[index-1]).risk_score<obj(row).risk_score)),candidates:candidates.map(row=>({id:textValue(obj(row).id),type:textValue(obj(row).type),target:textValue(obj(row).target),score:fmt(obj(row).risk_score),probes:strings(obj(row).predicted_probes),tried:boolText(obj(row).tried),selected:typeof raw.chosen==='string'&&obj(row).id===raw.chosen}))};
}
export function predictionPresentation(value) {
  const raw=obj(value);
  const check=value=>value===true?'Matches prediction':value===false?'Does not match':'Not available';
  return {right:fmt(raw.right),total:fmt(raw.total),items:arr(raw.items).map(row=>{
    const item=obj(row),predicted=obj(item.predicted),checks=obj(item.check);
    return {id:textValue(item.id),correct:item.correct===true?'Correct':item.correct===false?'Incorrect':'Not available',rows:[{name:'Affected probes',prediction:strings(predicted.probes_affected),check:check(checks.probes)},{name:'Recovery',prediction:boolText(predicted.recovers),check:check(checks.recovers)},{name:'Data loss',prediction:boolText(predicted.data_loss),check:check(checks.data_loss)}]};
  })};
}
export function impactPresentation(value) {
  const raw=obj(value);
  return {experiment:textValue(raw.experiment),summary:textValue(raw.summary),lost:fmt(raw.votes_lost),accepted:fmt(raw.votes_accepted),outage:fmt(raw.outage_s,' s'),failed:fmt(raw.failed_requests_pct,'%')};
}
