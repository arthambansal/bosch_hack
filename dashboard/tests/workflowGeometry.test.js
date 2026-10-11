import { test } from 'node:test';
import assert from 'node:assert/strict';
import { WORKFLOW_NODES, WORKFLOW_ROUTES } from '../src/workflow.js';
import { build } from 'esbuild';

function points(path) {
 const parts=[...path.matchAll(/([MHV])([0-9 ]+)/g)];let x=0,y=0;
 return parts.map(([,command,values])=>{const n=values.trim().split(/ +/).map(Number);if(command==='M'){[x,y]=n;}else if(command==='H')x=n[0];else y=n[0];return [x,y];});
}
function boundary(node,[x,y]) {
 return ((x===node.x||x===node.x+142)&&y>=node.y&&y<=node.y+80)||((y===node.y||y===node.y+80)&&x>=node.x&&x<=node.x+142);
}
test('every allowed route joins source and destination boundaries without traversing node interiors',()=>{
 assert.equal(WORKFLOW_ROUTES.length,18);
 for(const route of WORKFLOW_ROUTES){
  const vertices=points(route.path),from=WORKFLOW_NODES.find(n=>n.id===route.from),to=WORKFLOW_NODES.find(n=>n.id===route.to);
  if(from)assert.ok(boundary(from,vertices[0]),`${route.from} start`);
  if(to)assert.ok(boundary(to,vertices.at(-1)),`${route.to} end`);
  for(let i=1;i<vertices.length;i++)for(const node of WORKFLOW_NODES){
   const [a,b]=[vertices[i-1],vertices[i]];
   const crosses=a[0]===b[0]?a[0]>node.x&&a[0]<node.x+142&&Math.max(a[1],b[1])>node.y&&Math.min(a[1],b[1])<node.y+80:a[1]>node.y&&a[1]<node.y+80&&Math.max(a[0],b[0])>node.x&&Math.min(a[0],b[0])<node.x+142;
   assert.equal(crosses,false,`${route.from}->${route.to} crosses ${node.id}`);
  }
 }
});
const bundle=await build({stdin:{contents:`import React from 'react';import {renderToString} from 'react-dom/server';import AgentWorkflow from './src/components/AgentWorkflow.jsx';export function render(state){return renderToString(React.createElement(AgentWorkflow,{state,connected:true}));}`,resolveDir:process.cwd()},bundle:true,write:false,platform:'node',format:'esm',packages:'external'});
let source=bundle.outputFiles[0].text;
for(const name of ['react','react-dom','react-dom/server'])source=source.replaceAll(`from "${name}"`,`from ${JSON.stringify(import.meta.resolve(name))}`);
const {render}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
test('mocked active-step updates preserve paths, node boxes, and marker connections',()=>{
 let expected;
 for(const agent_active of ['cartographer','experimenter','human','executor','evaluator','diagnostician','remediator','verifier','reporter']){
  const html=render({run_status:'running',phase:'running',agent_active});
  const paths=[...html.matchAll(/<path[^>]* d="([^"]+)"[^>]*data-from=/g)].map(m=>m[1]);
  expected??=paths;assert.deepEqual(paths,expected);
  assert.equal((html.match(/<foreignObject /g)||[]).length,10);
  assert.equal((html.match(/is-active/g)||[]).length,1);
  const id=html.match(/<marker id="([^"]+)"/)[1];assert.ok(html.includes(`marker-end="url(#${id})"`));
  assert.match(html,/markerUnits="userSpaceOnUse"/);
 }
 const stopped=render({run_status:'stopped',phase:'running',agent_active:'executor'});
 assert.doesNotMatch(stopped,/is-active/);
});
