import React, { useState } from 'react';
import { fixesPresentation, memoryPresentation, planPresentation, predictionPresentation, impactPresentation, mysteryPresentation } from '../p1Model.js';
import { timestamp } from '../truthModel.js';
import { SectionHeading } from './ui.jsx';
import { useControls } from './ControlProvider.jsx';
import ControlFeedback from './ControlFeedback.jsx';
import { day2Api } from '../api/day2Api.js';
import InfoTooltip from './InfoTooltip.jsx';

function Panel({ id, eyebrow, title, description, children }) {
  return <section className="surface p1-panel" aria-labelledby={id}><SectionHeading id={id} eyebrow={eyebrow} title={title} description={description}/><div className="panel-body">{children}</div></section>;
}
function Readouts({ items }) {
  return <dl className="p1-readouts">{items.map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
}
const Missing=()=> <p className="missing-data">Not available</p>;

export function MysteryPanel({ live }) {
  const data=mysteryPresentation(live.state.mystery),controls=useControls();
  const [choice,setChoice]=useState('');
  const [startNote,setStartNote]=useState('');
  async function startEngine(){
    setStartNote('Starting the voting app and the Mystery engine. This takes about 20 seconds; the fault menu appears here when it is ready.');
    try { const r=await day2Api.startMystery(live); setStartNote(r.alreadyRunning ? 'The Mystery engine is already running. Waiting for its menu.' : 'Started. Waiting for the menu. If nothing appears within a minute, see runs/mystery_consumer.log.'); }
    catch(error) { setStartNote(error?.code==='stop_file_present' ? 'A STOP file exists. Delete the file named STOP in the project folder, then press Start again.' : (error?.message || 'Could not start Mystery Mode.')); }
  }
  const selectedValid=choice==='random' ? data.menu.length>0 : data.menu.some(item=>item.id===choice);
  return <Panel id="mystery-title" eyebrow="BLIND DIAGNOSIS LAB" title="Mystery Mode" description="Choose a sandbox fault. Agents must identify it from evidence; the backend controls injection and reveal.">
    <Readouts items={[["Published state",data.state],["Trial",data.trial],["Chosen by",data.chosenBy]]}/>
    <div className="mystery-selection"><label htmlFor="mystery-choice">Allowed faults</label><select id="mystery-choice" value={selectedValid?choice:''} onChange={event=>setChoice(event.target.value)} disabled={!controls?.mysteryAvailable}><option value="">Select a published fault</option>{data.menu.length>0 && <option value="random">Random allowed fault</option>}{data.menu.map(item=><option key={item.id} value={item.id}>{item.label} · {item.fault} / {item.target}</option>)}</select><button className="p1-primary" disabled={!controls?.mysteryAvailable || !selectedValid} onClick={()=>controls.openMysteryDialog(choice)}>Break it yourself</button></div>
    <p className="p1-note">Explicit confirmation is required. Submission needs a fresh live idle trial, an allowed menu, and no conflicting control request. Fixture snapshots cannot submit.</p>
    {!data.menu.length && <div className="missing-data"><p>Allowed menu: Not available. The Mystery engine is not running yet.</p><button type="button" onClick={startEngine} disabled={live?.status!=='connected'||live?.source==='fixture'}>Start Mystery Mode</button>{startNote && <p role="status">{startNote}</p>}<p>Terminal alternative: <code>python3 chaospilot.py mystery --wait</code></p></div>}
    <ControlFeedback result={controls?.mysteryResult}/>
    <details className="p1-details"><summary>Published menu and trial evidence</summary>{data.menu.length ? <ul>{data.menu.map(item=><li key={item.id}><code>{item.id}</code> — {item.label} · {item.fault} / {item.target}</li>)}</ul> : <Missing/>}<Readouts items={[["Injected at",timestamp(data.injectedAt)],["Detected at",timestamp(data.detectedAt)],["Diagnosed at",timestamp(data.diagnosedAt)],["Detected by",data.detectedBy]]}/></details>
    <div className="mystery-results"><article><h3>Published guess · not the answer</h3>{data.guess ? <><Readouts items={[["Fault",data.guess.fault],["Target",data.guess.target],["Confidence",data.guess.confidence],["Memory hit",data.guess.memoryHit]]}/><p>{data.guess.rootCause}</p><h4>Evidence</h4>{data.guess.evidence.length ? <ul>{data.guess.evidence.map((item,i)=><li key={i}>{item}</li>)}</ul>:<Missing/>}<details className="p1-details"><summary>Top-three guesses</summary>{data.guess.top3.length ? <ol>{data.guess.top3.map((item,i)=><li key={i}>{item.fault} / {item.target} · confidence {item.confidence}</li>)}</ol> : <Missing/>}</details></> : <p className="missing-data">Not available — waiting for a published diagnosis.</p>}</article>
    <article><h3>Backend reveal</h3>{data.answer ? <><Readouts items={[["Answer fault",data.answer.fault],["Answer target",data.answer.target],["Top-one correct",data.correct.top1],["Top-three correct",data.correct.top3],["Target correct",data.correct.target]]}/></> : <p className="missing-data">Not available — answer and correctness are withheld until state is revealed.</p>}</article></div>
    <h3>Published accuracy counters</h3><Readouts items={[["Trials",data.accuracy.trials],["Top-one correct trials",data.accuracy.top1],["Top-three correct trials",data.accuracy.top3],["Target correct trials",data.accuracy.target]]}/>
  </Panel>;
}

export function FixesPanel({ fixes, id='fixes-title', compact=false }) {
  const records=fixesPresentation(fixes);
  return <Panel id={id} eyebrow="REPORTED REMEDIATION" title="Findings → fixes" description="Backend proposals and verification results. This dashboard does not apply patches.">
    {records.length ? <div className="fix-list">{records.map((fix,i)=><article className="fix-entry" key={i}><div className="fix-entry-heading"><div><code>{fix.id}</code><h3>{fix.title}</h3></div><span className={`fix-status ${(fix.rollbackFailed||fix.rollbackInconsistent)?'status-rollback-failed':`status-${fix.status}`}`}>{fix.rollbackFailed?'Rollback failed':fix.rollbackInconsistent?'Inconsistent rollback evidence':fix.status}</span></div>{(fix.rollbackFailed||fix.rollbackInconsistent) && <div className="rollback-failure"><p>{fix.rollbackInconsistent?'Backend rollback failure contradicts its status; recovery is not confirmed.':'Rollback did not complete; recovery is not confirmed.'}</p>{fix.worse ? <div className="data-table-scroll" tabIndex="0" role="region" aria-label={`Worse RPN comparison for ${fix.id}`}><table className="evidence-table"><caption>Published worse comparison</caption><thead><tr><th>Experiment</th><th>Before</th><th>After</th></tr></thead><tbody><tr><td>{fix.worse.id}</td><td>{fix.worse.before}</td><td>{fix.worse.after}</td></tr></tbody></table></div> : <p className="missing-data">Worse comparison: Not available</p>}</div>}<p>{fix.reason}</p>{fix.untested.length>0 && <p className="p1-note">Not re-tested: {fix.untested.join(', ')} (run stopped or budget reached), so this verdict is not proven either way.</p>}<p className="p1-note">Kind: {fix.kind} · Experiments: {fix.for}{fix.kind==='code_suggestion'?' · Read-only code suggestion':''}</p>{fix.inconsistent && <p className="critical-text">Inconsistent backend record: code suggestions must remain proposed. Verification is not inferred.</p>}
    {compact ? <p className="p1-note">Published RPN comparisons: {fix.rpn.length || 'Not available'}. Full comparison and read-only diff are in Recovery.</p> : <><h4>RPN before / after <InfoTooltip term="RPN"/></h4>{fix.rpn.length ? <div className="data-table-scroll" tabIndex="0" role="region" aria-label={`RPN comparison for ${fix.id}`}><table className="evidence-table"><thead><tr><th>Experiment</th><th>Before</th><th>After</th></tr></thead><tbody>{fix.rpn.map((row,index)=><tr key={index}><td>{row.id}</td><td>{row.before}</td><td>{row.after}</td></tr>)}</tbody></table></div> : <Missing/>}<details className="p1-details"><summary>Read-only proposed diff</summary><pre className="raw-evidence">{fix.diff}</pre></details></>}</article>)}</div> : <Missing/>}
  </Panel>;
}

export function MemoryPanel({ memory }) {
  const data=memoryPresentation(memory);
  return <Panel id="memory-title" eyebrow="MEASURED REUSE" title="Failure memory" description="Only the last published match is shown. Similarity is not confidence."><Readouts items={[["Memory-hit status",data.status],["Stored signatures",data.signatures],["Similarity",data.similarity],["Measured time saved",data.saved]]}/><details className="p1-details"><summary>Published match evidence</summary><Readouts items={[["Experiment",data.experiment],["Signature",data.signature],["Seen in run",data.run]]}/><p>{data.rootCause}</p></details></Panel>;
}

export function PlanPanel({ plan }) {
  const data=planPresentation(plan);
  return <Panel id="plan-title" eyebrow="BACKEND PLANNING" title="Ranked experiment plan" description="Published candidate order, risk scores, and selection rationale. Predictions are not measurements."><p className="p1-rationale">{data.reason}</p><Readouts items={[["Turn",data.turn],["Chosen candidate",data.chosen],["Types covered",data.covered],["Types required",data.required]]}/>{data.invalid && <p className="critical-text">Incomplete or invalid ranking. Published order is preserved; no ranking is reconstructed.</p>}
  {data.candidates.length ? <details className="p1-details" open><summary>Published candidates</summary><div className="data-table-scroll" tabIndex="0" role="region" aria-label="Ranked experiment candidates"><table className="evidence-table"><thead><tr><th>Published position</th><th>Candidate</th><th>Fault / target</th><th>Risk score</th><th>Predicted probes</th><th>Tried</th></tr></thead><tbody>{data.candidates.map((item,index)=><tr key={index} className={item.selected?'plan-selected':''}><td>{index+1}</td><td>{item.id}{item.selected && <span className="fix-status">Chosen</span>}</td><td>{item.type} / {item.target}</td><td>{item.score}</td><td>{item.probes}</td><td>{item.tried}</td></tr>)}</tbody></table></div></details> : <Missing/>}</Panel>;
}

export function PredictionsPanel({ predictions }) {
  const data=predictionPresentation(predictions);
  return <Panel id="predictions-title" eyebrow="PREDICTION CHECKS" title="Predicted vs checked" description="Checks report whether measured outcomes matched each prediction. No missing checks are inferred."><Readouts items={[["Backend right counter",data.right],["Backend total counter",data.total]]}/>
  {data.items.length ? <div className="prediction-list">{data.items.map((item,index)=><details key={index} className="p1-details" open><summary>{item.id} · {item.correct}</summary><div className="data-table-scroll" tabIndex="0" role="region" aria-label={`Prediction checks for ${item.id}`}><table className="evidence-table"><thead><tr><th>Outcome</th><th>Predicted</th><th>Backend check</th></tr></thead><tbody>{item.rows.map(row=><tr key={row.name}><td>{row.name}</td><td>{row.prediction}</td><td>{row.check}</td></tr>)}</tbody></table></div></details>)}</div> : <Missing/>}</Panel>;
}

export function ImpactPanel({ impact }) {
  const data=impactPresentation(impact);
  return <Panel id="impact-title" eyebrow="HUMAN IMPACT" title="What users experienced" description={`Published experiment: ${data.experiment}. No missing measurements are replaced with zero.`}><Readouts items={[["Votes lost",data.lost],["Votes accepted",data.accepted],["Outage duration",data.outage],["Failed requests",data.failed]]}/><p className="p1-rationale">{data.summary}</p></Panel>;
}
