import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { fixesPresentation } from '../src/p1Model.js';

const bundle=await build({stdin:{contents:`import React from 'react';import {renderToString} from 'react-dom/server';import {FixesPanel} from './src/components/P1Panels.jsx';export function render(fixes,compact=false){return renderToString(React.createElement(FixesPanel,{fixes,compact}));}`,resolveDir:process.cwd(),loader:'jsx'},bundle:true,write:false,format:'esm',platform:'node',packages:'external'});
let source=bundle.outputFiles[0].text;
for(const name of ['react','react-dom','react-dom/server'])source=source.replaceAll(`from "${name}"`,`from ${JSON.stringify(import.meta.resolve(name))}`);
const {render}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const fix={id:'F1',title:'Restart worker',kind:'compose',status:'applied',why:'Published evidence',for:['E3'],rpn:[],rollback_failed:true,worse:{id:'E3',before:630,after:700}};

test('failed rollback keeps backend status and renders red failure with published worse values in both layouts',()=>{
  const original=structuredClone(fix),model=fixesPresentation([fix])[0];
  assert.equal(model.status,'applied');assert.equal(model.rollbackFailed,true);assert.deepEqual(model.worse,{id:'E3',before:'630',after:'700'});
  for(const compact of [false,true]) {
    const html=render([fix],compact);
    assert.match(html,/status-rollback-failed">Rollback failed/);assert.match(html,/recovery is not confirmed/);
    assert.match(html,/<td>E3<\/td><td>630<\/td><td>700<\/td>/);assert.match(html,/aria-label="Worse RPN comparison for F1"/);
    assert.doesNotMatch(html,/status-rolled_back|status-verified|status-applied/);
  }
  assert.deepEqual(fix,original);
});
test('failed rollback without worse evidence never invents comparison values',()=>{
  const input={...fix,worse:null};assert.equal(fixesPresentation([input])[0].worse,null);
  const html=render([input]);assert.match(html,/Rollback failed/);assert.match(html,/Worse comparison: Not available/);assert.doesNotMatch(html,/Published worse comparison|<td>0<\/td>|630|700/);
});
test('successful rollback and existing applied/verified records retain their status without failure badge',()=>{
  for(const status of ['rolled_back','applied','verified']) {
    const html=render([{...fix,status,rollback_failed:false,worse:null}]);assert.match(html,new RegExp(`status-${status}`));assert.doesNotMatch(html,/Rollback failed|rollback-failure|Published worse comparison/);
  }
});
test('historical and partial fields require exact failure boolean and do not fabricate measurements',()=>{
  for(const input of [null,{}, {status:'applied'}, {...fix,rollback_failed:undefined}, {...fix,rollback_failed:'true'}])assert.doesNotMatch(render([input]),/Rollback failed/);
  const html=render([{...fix,worse:{id:'E3',before:0}}]);assert.match(html,/<td>E3<\/td><td>0<\/td><td>Not available<\/td>/);
  assert.match(render(undefined),/Not available/);
});
test('failure evidence stays escaped and overrides any contradictory success badge',()=>{
  const html=render([{...fix,status:'rolled_back',worse:{id:'<script>bad</script>',before:null,after:null}}]);
  assert.match(html,/Rollback failed/);assert.doesNotMatch(html,/status-rolled_back|<script>/);assert.match(html,/&lt;script&gt;/);
});
