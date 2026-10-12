const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');

test('keeper review starts unknown and does not imply verified history',()=>{
  const {WorkspaceKeeper}=loadComponent('src/components/WorkspaceKeeper.tsx');
  const html=renderToStaticMarkup(React.createElement(WorkspaceKeeper,{league:'1398509004950376448',players:[]}));
  assert.match(html,/Manual evidence review/);
  assert.match(html,/round 6 costs round 5/);
  assert.match(html,/Load archived draft evidence/);
  assert.match(html,/Required evidence · 0\/5 supplied/);
  assert.match(html,/missing provider flag is not/);
  assert.match(html,/already a keeper in the draft season/);
  assert.match(html,/Supplied is not verified or eligible/);
  assert.match(html,/disabled=""[^>]*>Check eligibility and cost/);
  assert.doesNotMatch(html,/eligible under supplied evidence/);
  const other=renderToStaticMarkup(React.createElement(WorkspaceKeeper,{league:'other',players:[]}));
  assert.match(other,/not configured/);
  assert.doesNotMatch(other,/<select/);
});

test('initial research shell does not render comparison or trade selectors', () => {
  const target = {exports:{}};
  const fail = () => {throw new Error('Closed research tool rendered eagerly');};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/components/WorkspaceResearchTools.tsx','utf8'), {
    compilerOptions:{module:ts.ModuleKind.CommonJS, jsx:ts.JsxEmit.ReactJSX},
  }).outputText, {exports:target.exports, require:(id) => {
    if(id === '@/components/WorkspaceComparison') return {WorkspaceComparison:fail};
    if(id === '@/components/WorkspaceTrade') return {WorkspaceTrade:fail};
    return require(id);
  }});
  const html=renderToStaticMarkup(React.createElement(target.exports.WorkspaceResearchTools,{overview:{}}));
  assert.match(html,/Open player comparison/);
  assert.match(html,/Open trade research/);
  assert.doesNotMatch(html,/<select|<option/);
});

function loadComponent(path, overrides={}) {
  const target={exports:{}};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path,'utf8'),{
    compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2020},
  }).outputText,{exports:target.exports,URLSearchParams,require:id=>overrides[id]??require(id)});
  return target.exports;
}
test('research status exposes blockers without claiming promoted probabilities',()=>{
  const {WorkspaceResearchStatus}=loadComponent('src/components/WorkspaceResearchStatus.tsx');
  const item={status:'current',generated_at:'2026-10-10T00:00:00Z',requested_weeks:[5,6,7],new_captures:0,
    counts:[],blockers:[{reason:'missing_future_week_evidence',count:3}]};
  const html=renderToStaticMarkup(React.createElement(WorkspaceResearchStatus,{research:{retention:item,specialists:item}}));
  assert.match(html,/Not promoted/);
  assert.match(html,/missing future week evidence/);
  assert.match(html,/Requested weeks: 5, 6, 7/);
  assert.match(html,/New captures in last run: 0/);
});
test('validation readiness reports distinct repair targets without inferring DNP',()=>{
  const {FantasyValidationStatus}=loadComponent('src/components/FantasyValidationStatus.tsx');
  const html=renderToStaticMarkup(React.createElement(FantasyValidationStatus,{data:{prospective:{result_backlog:{
    blocked_captures:684,unique_player_games:112,unique_games:45,additional_captures:572,
    player_games_by_blocker:{missing_player_results:112}}}}}));
  assert.match(html,/684 blocked captures represent 112 distinct player-games across 45 games/);
  assert.match(html,/572 repeated captures are not additional missing outcomes/);
  assert.match(html,/do not establish zero points or nonparticipation/);
  assert.doesNotMatch(renderToStaticMarkup(React.createElement(FantasyValidationStatus,{data:{}})),/Missing-result repair targets/);
});
test('trade picker caps rendered results and does not offer uncorroborated players',()=>{
  const helpers=loadComponent('src/lib/workspace.ts');
  const {WorkspaceTradePicker}=loadComponent('src/components/WorkspaceTradePicker.tsx',{'@/lib/workspace':helpers});
  const players=Array.from({length:30},(_,i)=>({player_id:String(i),name:`Player ${i}`,position:'QB',team:'DEN',roster_names:['Team'],roster_id:'one',ownership:'your_roster'}));
  players.push({...players[0],player_id:'unknown',name:'Unknown owner',ownership:'unknown'});
  const html=renderToStaticMarkup(React.createElement(WorkspaceTradePicker,{label:'A',players,ids:[],other:[],busy:false,onChange:()=>{}}));
  assert.equal((html.match(/aria-label="Add Player/g)||[]).length,12);
  assert.doesNotMatch(html,/Add Unknown owner/);
  assert.match(html,/30 eligible matches/);
  assert.equal((html.match(/<select/g)||[]).length,1);
});
test('closed trade adjustment plans do not construct their player lists',()=>{
  const helpers=loadComponent('src/lib/workspace.ts');
  const {WorkspaceTrade}=loadComponent('src/components/WorkspaceTrade.tsx',{
    '@/lib/workspace':helpers,
    'next/navigation':{useRouter:()=>({refresh:()=>{}})},
    '@/components/WorkspaceTradePicker':{WorkspaceTradePicker:()=>React.createElement('div')},
    '@/components/SnapshotWindow':{SnapshotWindow:({children})=>children},
  });
  const html=renderToStaticMarkup(React.createElement(WorkspaceTrade,{overview:{league_id:'a',generated_at:'now',comparison_players:[]}}));
  assert.doesNotMatch(html,/<select/);
  assert.match(html,/Uneven-trade add\/drop plans/);
  assert.match(html,/disabled=""[^>]*>Evaluate saved roster impact/);
});
test('waiver alternatives group by added position and keep each corresponding drop',()=>{
  const {WorkspaceRoster}=loadComponent('src/components/WorkspaceRoster.tsx',{'@/lib/workspace':loadComponent('src/lib/workspace.ts')});
  const player=(name,position)=>({player_id:name,name,position,team:'DEN',points:0,source:'estimated',identity_status:'exact',history_status:'unknown',missing_scoring_keys:[]});
  const move=(name,position,gain)=>({add:player(name,position),drop:player(`Drop ${name}`,'RB'),unstarted_slot_gain:gain,equivalent_drops:[player('Alternative','RB')]});
  const html=renderToStaticMarkup(React.createElement(WorkspaceRoster,{section:'waivers',overview:{roster_players:[],waivers:{status:'lock_preserving_candidate',excluded_moves:0,moves:[move('Low','QB',1),move('High','QB',3),move('Other','TE',2)]}}}));
  assert.match(html,/QB · 2 alternatives/);
  assert.match(html,/TE · 1 alternatives/);
  assert.ok(html.indexOf('Research High')<html.indexOf('Research Low'));
  assert.match(html,/for Drop High/);
  assert.match(html,/Drop decision unresolved/);
  assert.match(html,/This is not a drop recommendation/);
  assert.match(html,/Other drops with the same weekly gain/);
  assert.match(html,/Research High for Alternative/);
  assert.match(html,/not a rest-of-season waiver ranking/);
});

test('lineup review distinguishes reassignment from addition and avoids mismatched slot pairing',()=>{
  const {WorkspaceLineupReview}=loadComponent('src/components/WorkspaceLineupReview.tsx',{'@/lib/workspace':loadComponent('src/lib/workspace.ts')});
  const p=(id,slot,points=0)=>({player_id:id,name:id,slot,points,source:'estimated',locked:false});
  const overview={league_id:'a',lineup_status:'candidate',lineup_changes:{reason:'Review complete lineup'},
    matchup:{mine:{starters:[p('one','RB'),p('two','FLEX')]}},starters:[p('two','RB'),p('three','FLEX',null)]};
  const render=o=>renderToStaticMarkup(React.createElement(WorkspaceLineupReview,{overview:o}));
  const html=render(overview);
  assert.match(html,/Slot reassignment/);
  assert.match(html,/Candidate addition/);
  assert.match(html,/0.0 pregame points/);
  assert.match(html,/Unknown points/);
  assert.match(html,/player=one&amp;compare=two/);
  const mismatch=render({...overview,starters:[p('two','WR')]});
  assert.match(mismatch,/Current slot unknown/);
  assert.match(mismatch,/slot layouts differ/);
  assert.doesNotMatch(mismatch,/Compare evidence/);
});
