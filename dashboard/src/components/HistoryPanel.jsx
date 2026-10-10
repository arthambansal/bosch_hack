import React, { useEffect, useState } from 'react';
import { day2Api } from '../api/day2Api.js';
import { preserveSelection, replayIndex, recordedTime } from '../historyModel.js';

export function RecordedReplay({ lines, active }) {
  const [index,setIndex] = useState(0), [playing,setPlaying] = useState(false), [speed,setSpeed] = useState(1);
  useEffect(()=>{ if (!active) setPlaying(false); },[active]);
  useEffect(()=>{
    if (!playing || !active || index >= lines.length-1) { if (playing) setPlaying(false); return; }
    const timer=setTimeout(()=>setIndex(previous=>replayIndex(previous,'next',lines.length)),1000/speed);
    return ()=>clearTimeout(timer);
  },[playing,active,index,lines.length,speed]);
  const move=action=>{setPlaying(false);setIndex(previous=>replayIndex(previous,action,lines.length));};
  const start=Math.max(0,index-20), end=Math.min(lines.length,start+41);
  return <section className="surface history-replay"><div className="panel-body"><h2>Recorded Event Replay</h2><p className="p1-note">Recorded text only. Playback advances one event per reading interval, not elapsed run time. Live status and controls above refer to the current run.</p>
    {!lines.length ? <p>No recorded events.</p> : <><div className="history-actions"><button onClick={()=>setPlaying(value=>!value)} disabled={!active || index===lines.length-1}>{playing?'Pause':'Play'}</button><button onClick={()=>move('back')} disabled={index<=0}>Step backward</button><button onClick={()=>move('next')} disabled={index>=lines.length-1}>Step forward</button><button onClick={()=>move('reset')}>Reset</button><label>Reading speed <select value={speed} onChange={event=>setSpeed(Number(event.target.value))}>{[0.5,1,2,4].map(value=><option key={value} value={value}>{value}×</option>)}</select></label></div>
    <label className="replay-position">Event {index+1} of {lines.length}<input aria-label="Recorded event position" type="range" min="0" max={lines.length-1} value={index} onChange={event=>{setPlaying(false);setIndex(Number(event.target.value));}}/></label>
    <pre className="selected-recorded-event" aria-label="Selected recorded event">{lines[index] || '(Empty recorded line)'}</pre>
    <p className="p1-note">Showing events {start+1}–{end}; original file order. Recorded clock times have no supplied date or timezone.</p><ol className="recorded-events" start={start+1}>{lines.slice(start,end).map((line,offset)=>{const position=start+offset,time=recordedTime(line);return <li key={position}><button aria-current={position===index?'step':undefined} onClick={()=>{setPlaying(false);setIndex(position);}}><span>Event {position+1} · {time ? `Recorded clock ${time}`:'Timestamp not available'}</span><pre>{line || '(Empty recorded line)'}</pre></button></li>;})}</ol></>}
  </div></section>;
}

export function ReportViewer({ report }) {
  const [feedback,setFeedback]=useState('');
  async function copy() { try { await navigator.clipboard.writeText(report);setFeedback('Report copied.'); } catch {setFeedback('Copy unavailable. Select the report text to copy manually.');} }
  function download() {
    const url=URL.createObjectURL(new Blob([report],{type:'text/markdown;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='report.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return <section className="surface"><div className="panel-body"><h2>Recorded report.md</h2><p className="p1-note">Original Markdown shown as escaped text. Headings, tables, lists, and code remain readable in their source form.</p>{!report.trim() ? <p>Report file is empty.</p> : <><div className="history-actions"><button onClick={copy}>Copy report</button><button onClick={download}>Download report.md</button></div><p role="status">{feedback}</p><pre className="report-source" tabIndex="0" aria-label="Recorded Markdown report">{report}</pre></>}</div></section>;
}

export default function HistoryPanel({ active, fixture }) {
  const [listing,setListing]=useState({status:'idle',rows:[],error:''}), [selected,setSelected]=useState(''), [revision,setRevision]=useState(0);
  const [evidence,setEvidence]=useState({name:'',events:{status:'idle'},report:{status:'idle'}});
  useEffect(()=>{
    if (!active || fixture) return;
    const controller=new AbortController();let disposed=false;
    const deadline=setTimeout(()=>controller.abort(),10000);
    setListing(previous=>({...previous,status:'loading',error:''}));
    day2Api.runs({signal:controller.signal}).then(rows=>{if(!disposed){setListing({status:'ready',rows,error:''});setSelected(previous=>preserveSelection(rows,previous));}}).catch(()=>{if(!disposed)setListing(previous=>({...previous,status:'error',error:'Run history unavailable. Refresh to retry; retained rows are stale.'}));}).finally(()=>clearTimeout(deadline));
    return ()=>{disposed=true;clearTimeout(deadline);controller.abort();};
  },[active,fixture,revision]);
  useEffect(()=>{
    if (!active || fixture || !selected) return;
    const controller=new AbortController();let disposed=false;
    const deadline=setTimeout(()=>controller.abort(),10000);
    setEvidence({name:selected,events:{status:'loading'},report:{status:'loading'}});
    Promise.allSettled(['events','report'].map(kind=>day2Api[kind](selected,{signal:controller.signal}).then(value=>{if(!disposed)setEvidence(previous=>({...previous,[kind]:{status:'ready',value}}));}).catch(error=>{if(!disposed)setEvidence(previous=>({...previous,[kind]:{status:error.status===404?'missing':'error'}}));}))).then(()=>clearTimeout(deadline));
    return ()=>{disposed=true;clearTimeout(deadline);controller.abort();};
  },[active,fixture,selected,revision]);
  const current=evidence.name===selected?evidence:null;
  return <div className="history-workspace"><section className="surface"><div className="panel-body"><div className="history-heading"><h2>Run history</h2><button className="text-button" onClick={()=>setRevision(value=>value+1)} disabled={fixture || listing.status==='loading'}>Refresh history</button></div><p className="p1-note">Read-only archived evidence. Times are derived from runtime directory names, in recorded local calendar time; timezone is unavailable. Server newest-first order is preserved.</p>
    {fixture ? <p>FIXTURE DATA — archived history requests are disabled.</p> : <><p role="status">{listing.status==='loading'?'Loading run history…':listing.error || (listing.status==='idle'?'Open History to load recorded runs.':!listing.rows.length?'No recorded runs.':'')}</p>{listing.rows.length>0 && <><label htmlFor="history-run">Recorded run</label><select id="history-run" value={selected} onChange={event=>setSelected(event.target.value)}>{listing.rows.map(row=><option key={row.name} value={row.name}>{row.name} · {row.started_at || 'Not available'} · {row.has_report?'Report available':'No report generated'}</option>)}</select>{listing.status!=='ready' && <p className="p1-note">Retained listing — availability is unconfirmed.</p>}</>}</>}
  </div></section>
  {!fixture && selected && <div className="history-evidence" key={selected}><p className="history-banner">ARCHIVED EVIDENCE · {selected} · independent of the live snapshot</p>{['events','report'].map(kind=>{const item=current?.[kind];if(item?.status==='ready')return kind==='events'?<RecordedReplay key={`${selected}-${revision}`} lines={item.value.lines} active={active}/>:<ReportViewer key={`${selected}-report`} report={item.value}/>;return <section key={kind} className="surface"><div className="panel-body"><h2>{kind==='events'?'Recorded Event Replay':'Recorded report.md'}</h2><p role="status">{item?.status==='missing'?(kind==='report'?'No report generated (report.md absent).':'Event log not available.'):item?.status==='error'?'Evidence unavailable: network, read, or malformed-response error. Refresh history to retry.':'Loading recorded evidence…'}</p></div></section>;})}</div>}
  </div>;
}
