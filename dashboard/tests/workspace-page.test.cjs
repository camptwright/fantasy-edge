const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');

function load(path, requireModule) {
  const target = {exports:{}};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path,'utf8'), {
    compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
  }).outputText,{exports:target.exports, require:requireModule, URLSearchParams});
  return target.exports;
}
const helpers=load('src/lib/workspace.ts',require);

async function page(tool, status='snapshot_available', view='fantasy') {
  const calls=[];
  const overview={status,generated_at:null,expires_at:null,week:5,starters:[],notes:[],comparison_players:[],league_id:'a',matchup:{mine:null},lineup_changes:{status:'withheld',reason:'No evidence'}};
  const fake = () => new Proxy({}, {get: (_, name) => typeof name === 'string' ? () => React.createElement('div',{'data-tool':name}) : undefined});
  const module=load('src/app/workspace/page.tsx',id => {
    if(id==='@/lib/workspace') return helpers;
    if(id==='next/link') return {default:({children,...props})=>React.createElement('a',{href:props.href},children)};
    if(id==='@/lib/fantasy-api') return {fantasyApi:async path=>{
      calls.push(path);
      return path.endsWith('/overview') ? overview : {items:[{league_id:'a',name:'My league',platform:'sleeper',sport:'nfl'}]};
    }};
    if(id==='@/components/SnapshotWindow') return {SnapshotWindow:({children})=>children,SnapshotRetry:()=>React.createElement('p',{'data-retry':'auto'})};
    if(id.startsWith('@/components/')) return fake();
    return require(id);
  });
  return {html:renderToStaticMarkup(await module.default({searchParams:Promise.resolve({tool,view,league:'a'})})),calls};
}
test('fantasy screens render only their requested tools with two bounded reads',async()=>{
  const expected={overview:['SeasonTiles','WorkspaceMatchup','WorkspaceAreTheyPlaying','QuickActions','WorkspaceDailyBrief','PositionStrength','WorkspaceOutlook'],startsit:['WorkspaceStartSit'],team:['WorkspaceAreTheyPlaying','WorkspaceRoster','WorkspaceLineupReview'],waivers:['WorkspaceResearchStatus','WorkspaceEngineWaivers','WorkspacePositionLadder','WorkspaceRoster'],players:['WorkspaceResearchStatus','WorkspaceComparison'],trade:['WorkspaceTradeIdeas','WorkspaceTrade'],league:['WorkspaceStandings','WorkspaceLeagueAnalyzer','PositionStrength'],recap:['WorkspaceRecap'],player:['WorkspacePlayerProfile']};
  for(const [tool,names] of Object.entries(expected)) {
    const {html,calls}=await page(tool);
    // Trade adds one bounded read for the win-win trade finder.
    // Trade adds the trade finder read; Overview and League add the standings read.
    assert.equal(calls.length,['trade','overview','league','recap'].includes(tool) ? 3 : 2);
    if(tool === 'recap') assert.match(calls[2],/\/recap$/);
    if(tool === 'trade') assert.match(calls[2],/\/trade-ideas$/);
    if(tool === 'overview' || tool === 'league') assert.match(calls[2],/\/standings$/);
    assert.deepEqual([...html.matchAll(/data-tool="([^"]+)"/g)].map(m=>m[1]),names);
    assert.match(html,new RegExp(`tool=${tool === 'player' ? 'team' : tool}`));
    assert.match(html,/aria-label="Fantasy tools"/);
  }
});
test('missing checkpoint never mounts research tools',async()=>{
  const {html}=await page('trade','updating');
  assert.doesNotMatch(html,/data-tool=/);
  assert.match(html,/data-retry="auto"/);
  assert.doesNotMatch(html,/Check for an updated snapshot/);
});
test('Today shows the daily review without rendering trade or player selectors',async()=>{
  const {html}=await page('trade','snapshot_available','today');
  assert.match(html,/data-tool="WorkspaceDailyBrief"/);
  assert.doesNotMatch(html,/data-tool="WorkspaceTrade"|data-tool="WorkspaceComparison"/);
});
