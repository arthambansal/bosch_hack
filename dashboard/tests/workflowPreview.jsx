import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import AgentWorkflow from '../src/components/AgentWorkflow.jsx';
import DependencyMap from '../src/components/DependencyMap.jsx';
import fixture from '../fixtures/gray_failure.json';
import '../src/styles/main.css';
import '../src/styles/slateConsole.css';
function Preview(){
 const [stage,setStage]=useState('executor'),[revision,setRevision]=useState(0);
 const state={...fixture,agent_active:stage,run_status:'running',phase:'running'};
 return <main style={{padding:24}}><h1>Mock graph transitions</h1><p>Static test data only. No polling, controls, experiment launch, or backend writes.</p><div className="history-actions">{['cartographer','experimenter','human','executor','evaluator','diagnostician','remediator','verifier','reporter'].map(step=><button key={step} onClick={()=>setStage(step)}>Mock {step}</button>)}<button onClick={()=>setRevision(n=>n+1)}>Repeat snapshot</button></div><p>Snapshot revision: {revision}</p><AgentWorkflow state={state} connected/><DependencyMap state={state} connected={false}/></main>;
}
createRoot(document.getElementById('root')).render(<Preview/>);
