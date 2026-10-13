const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const vm = require('node:vm');
const exportsObject = {};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/lib/workspace.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: exportsObject, URLSearchParams });
const { workspaceView, workspaceHref, fantasyHref } = exportsObject;
test('linked player research validates against current league catalog and encodes IDs',()=>{
  const {researchSelection,playerResearchHref}=exportsObject;
  const players=[{player_id:'a&compare=x'},{player_id:'b'}];
  const url=new URL(playerResearchHref('league','a&compare=x','b'),'http://localhost');
  assert.equal(url.searchParams.get('player'),'a&compare=x');
  assert.equal(url.searchParams.get('compare'),'b');
  assert.equal(researchSelection(players,'a&compare=x','b').right,'b');
  assert.equal(researchSelection(players,'missing','b').right,'');
  assert.equal(researchSelection(players,'missing','b').unavailable,true);
  assert.equal(researchSelection(players,'b','b').unavailable,true);
});
test('trade selection binds two distinct corroborated rosters and fails closed on stale packages', () => {
  const player=(id,owner,ownership='other_roster')=>({player_id:id,roster_id:owner,ownership,name:id,position:'QB',team:'DEN',roster_names:[owner??'Unknown']});
  const players=[player('a','one'),player('b','one'),player('c','two'),player('d','three'),player('free',null,'unrostered_snapshot'),player('conflict','one','unknown')];
  const {tradeCandidates,tradePackageOwner}=exportsObject;
  assert.equal(tradePackageOwner(players,['a','b']),'one');
  for(const ids of [[],['a','c'],['a','missing'],['a','a'],['conflict']]) assert.equal(tradePackageOwner(players,ids),null);
  assert.equal(tradeCandidates(players,['a'],['c'],'','all').map(p=>p.player_id).join(','),'b');
  assert.equal(tradeCandidates(players,[],['a'],'','all').map(p=>p.player_id).join(','),'c,d');
  assert.equal(tradeCandidates(players,['missing'],[],'','all').length,0);
  assert.equal(tradeCandidates(players,['a'],['b'],'','all').length,0);
  assert.equal(tradeCandidates(players,[],[],'den','two').map(p=>p.player_id).join(','),'c');
});
test('fantasy tool URLs are allowlisted and preserve encoded league context', () => {
  assert.equal(exportsObject.fantasyTool('trade'), 'trade');
  assert.equal(exportsObject.fantasyTool('invalid'), 'overview');
  const url = new URL(exportsObject.fantasyToolHref('waivers', 'league&tool=trade'), 'http://localhost');
  assert.equal(url.searchParams.get('tool'), 'waivers');
  assert.equal(url.searchParams.get('league'), 'league&tool=trade');
  assert.equal(url.searchParams.get('view'), 'fantasy');
});
test('daily review prioritizes evidence without treating zero as missing or inventing availability', () => {
  const overview = {status:'snapshot_available', roster_players:[
    {points:0, injury_status:null}, {points:10, injury_status:'ACTIVE'}, {points:null, injury_status:'Questionable'}],
    lineup_changes:{status:'available',start:[{}],reason:'Candidate only'}, waivers:{moves:[]}};
  const rows = exportsObject.dailyReview(overview);
  assert.equal(rows.length,4);
  assert.equal(rows[0].title,'1 player designation to review');
  assert.equal(rows[1].title,'1 unpriced roster player');
  assert.equal(rows[2].title,'1 candidate lineup change');
  assert.match(rows[0].detail,/Missing designations do not confirm availability/);
  assert.equal(exportsObject.dailyReview({...overview,status:'updating'}).length,0);
  assert.equal(exportsObject.dailyReview({...overview,roster_players:[]})[0].title,'Roster evidence unavailable');
});
test('daily review flags starters on bye next week, not players with no engine weeks', () => {
  const wk=(...weeks)=>weeks.map(week=>({week,points:10,environment:'market_line'}));
  const overview = {status:'snapshot_available', week:6, matchup:{mine:{starters:[{player_id:'a'},{player_id:'b'},{player_id:'c'}]}},
    roster_players:[{player_id:'a',name:'T.J. Hockenson',points:10,engine_weeks:wk(6,8,9)},{player_id:'b',name:'Has Game',points:10,engine_weeks:wk(6,7,8)},
      {player_id:'c',name:'Kicker',points:8,engine_weeks:[]},{player_id:'d',name:'Bench Bye',points:5,engine_weeks:wk(6,8)}],
    lineup_changes:{status:'withheld',start:[],reason:'r'}, waivers:{moves:[]}};
  const bye = exportsObject.dailyReview(overview).find(r => /bye/.test(r.title));
  assert.equal(bye.title,'1 starter on bye in week 7');
  assert.match(bye.detail,/T\.J\. Hockenson has no game next week/);
  assert.equal(bye.attention,true);
});
test('client research props exclude unrelated overview and roster fields', () => {
  const players=[];
  const result=exportsObject.researchContext({league_id:'league',generated_at:'timestamp',comparison_players:players,
    matchup:{},starters:[],waivers:{},roster_players:[],notes:['unneeded']});
  assert.equal(Object.keys(result).sort().join(','),'comparison_players,generated_at,league_id');
  assert.equal(result.comparison_players,players);
});
test('trade blockers give guidance with a safe unknown-code fallback', () => {
  const { tradeBlockerText } = exportsObject;
  assert.match(tradeBlockerText('snapshot_changed_refresh_before_comparing'), /Refresh/);
  assert.match(tradeBlockerText('incomplete_roster_or_availability'), /supporting roster/);
  assert.match(tradeBlockerText('uneven_trade_requires_explicit_add_drop_plan'), /zero/);
  assert.equal(tradeBlockerText('new_blocker'), 'Comparison withheld: new blocker.');
});
test('comparison search respects ownership and unknown metadata', () => {
  const { comparisonMatches } = exportsObject;
  const player = {name:'Test Player', position:'QB', team:null, ownership:'unknown'};
  assert.equal(comparisonMatches(player, '  test ', 'all'), true);
  assert.equal(comparisonMatches(player, 'qb', 'unknown'), true);
  assert.equal(comparisonMatches(player, '', 'unrostered_snapshot'), false);
  assert.equal(comparisonMatches(player, 'absent', 'all'), false);
});
test('unknown view defaults to Today', () => {
  assert.equal(workspaceView('invalid'), 'today');
  assert.equal(workspaceView('markets'), 'markets');
});
test('league context is encoded and cannot inject other parameters', () => {
  const link = new URL(workspaceHref('fantasy', 'a&view=settings'), 'http://localhost');
  assert.equal(link.searchParams.get('league'), 'a&view=settings');
  assert.equal(link.searchParams.get('view'), 'fantasy');
  assert.equal(fantasyHref('/fantasy', undefined), '/fantasy');
});
test('expired or invalid snapshot windows fail closed, including exact deadline', () => {
  const { snapshotRemainingMs } = exportsObject;
  const at = Date.parse('2026-10-03T10:00:00Z');
  assert.equal(snapshotRemainingMs('2026-10-03T10:00:00Z', at), 0);
  assert.equal(snapshotRemainingMs('2026-10-03T10:00:00Z', at + 1), 0);
  assert.equal(snapshotRemainingMs('2026-10-03T10:02:00Z', at), 120000);
  assert.equal(snapshotRemainingMs(null, at), 0);
  assert.equal(snapshotRemainingMs('invalid', at), 0);
});
