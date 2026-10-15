const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const helpers={};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/workspace.ts','utf8'),{
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020},
}).outputText,{exports:helpers,URLSearchParams});
function render(states) {
  let index=0;
  const module={exports:{}};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/components/WorkspaceComparison.tsx','utf8'),{
    compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
  }).outputText,{exports:module.exports,require:id=>{
    if(id==='react')return {...React,useState:initial=>[states[index++]??initial,()=>{}]};
    if(id==='@/lib/workspace')return helpers;
    if(id==='./WorkspaceRoleChanges')return {WorkspaceRoleChanges:()=>null};
    return require(id);
  }});
  const players=Array.from({length:25},(_,i)=>({player_id:String(i),name:`Player ${String(i).padStart(2,'0')}`,position:'QB',team:null,points:i===0?0:null,
    source:'estimated',ownership:'your_roster',roster_names:[],locked:false,ros_points:null,known_schedule_subtotal:null,ros_status:'withheld',
    known_remaining_games:null,unknown_kickoffs:null,through_week:null,history_status:'missing',complete_scored_games:null,missing_scoring_keys:[],injury_status:null,
    identity_status:'unknown',projection_observed_at:null,history_through:null,
    availability_status:'unconfirmed_missing_designation',distribution:{source:'assumed_specialist_default',status:'assumed_position_prior',observed_samples:0,reconciliation_samples:null,reconciliation_mismatches:null,assumed_prior:true}}));
  return renderToStaticMarkup(React.createElement(module.exports.WorkspaceComparison,{players}));
}
test('player results are paginated without hundreds of select options',()=>{
  const html=render([]);
  assert.equal((html.match(/aria-label="View Player/g)||[]).length,20);
  assert.equal((html.match(/<select/g)||[]).length,1);
  assert.match(html,/Page 1 of 2/);
  assert.match(html,/Pregame: 0.0/);
  assert.match(html,/Unknown \/ withheld/);
  const second=render(['','','','all',1]);
  assert.equal((second.match(/aria-label="View Player/g)||[]).length,5);
});
test('one player exposes identity, provenance and missing availability before the results',()=>{
  const html=render(['0']);
  assert.match(html,/Selected player evidence/);
  assert.match(html,/Canonical identity/);
  assert.match(html,/Projection observed/);
  assert.match(html,/Not supplied — availability unconfirmed/);
  assert.match(html,/Assumed positional prior — not measured player history or calibrated probability/);
  assert.match(html,/Scoring reconciliation checks \/ mismatches/);
  assert.ok(html.indexOf('Selected player evidence')<html.indexOf('Player search results'));
});
test('two players show an evidence comparison, not a winner',()=>{
  const html=render(['0','1']);
  assert.match(html,/Player 00 vs Player 01/);
  assert.match(html,/Evidence comparison — no winner or trade recommendation inferred/);
  assert.match(html,/Remove comparison/);
});
