const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');

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
    '@/components/WorkspaceTradeOutlook':{WorkspaceTradeOutlook:()=>React.createElement('div')},
  });
  const html=renderToStaticMarkup(React.createElement(WorkspaceTrade,{overview:{league_id:'a',generated_at:'now',comparison_players:[]}}));
  assert.doesNotMatch(html,/<select/);
  assert.match(html,/Uneven-trade add\/drop plans/);
  assert.match(html,/disabled=""[^>]*>Evaluate saved roster impact/);
});
test('waiver alternatives group by added position and keep each corresponding drop',()=>{
  const workspaceLib=loadComponent('src/lib/workspace.ts');
  const outlook=loadComponent('src/components/WorkspaceOutlook.tsx',{'@/lib/workspace':workspaceLib});
  const charts=loadComponent('src/components/OutcomeCharts.tsx',{'@/lib/workspace':workspaceLib});
  const {WorkspaceRoster}=loadComponent('src/components/WorkspaceRoster.tsx',{'@/lib/workspace':workspaceLib,'./WorkspaceOutlook':outlook,'./OutcomeCharts':charts});
  const player=(name,position)=>({player_id:name,name,position,team:'DEN',points:0,source:'estimated',identity_status:'exact',history_status:'unknown',missing_scoring_keys:[]});
  const move=(name,position,gain)=>({add:player(name,position),drop:player(`Drop ${name}`,'RB'),unstarted_slot_gain:gain,equivalent_drops:[player('Alternative','RB')]});
  const html=renderToStaticMarkup(React.createElement(WorkspaceRoster,{section:'waivers',overview:{roster_players:[],comparison_players:[],week:5,waivers:{status:'lock_preserving_candidate',excluded_moves:0,moves:[move('Low','QB',1),move('High','QB',3),move('Other','TE',2)]}}}));
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

function enginePlayer(id, extra={}) {
  return {player_id:id,name:id,position:'WR',team:'KC',points:null,source:'unknown',locked:false,injury_status:null,
    identity_status:'exact',ownership:'your_roster',roster_names:[],engine_status:'research',engine_week_points:10,
    engine_ros_points:50,engine_ros_games:5,engine_ros_lined_games:1,engine_generated_at:'2026-10-12T00:00:00Z',
    engine_weeks:[{week:6,points:10,environment:'market_line'},{week:8,points:12,environment:'team_average_no_line'}],
    ros_status:'unknown',ros_points:null,history_status:'unknown',missing_scoring_keys:[],
    distribution:{observed_samples:0,source:'unknown',assumed_prior:false},game_log:[],...extra};
}
test('roster outlook shows byes and unmodeled players as missing, never zero',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const {WorkspaceOutlook}=loadComponent('src/components/WorkspaceOutlook.tsx',{'@/lib/workspace':lib});
  const kicker=enginePlayer('K1',{position:'K',engine_status:'position_not_modeled',engine_weeks:[],engine_ros_points:null,engine_week_points:null});
  const html=renderToStaticMarkup(React.createElement(WorkspaceOutlook,{overview:{league_id:'a',week:6,
    roster_players:[enginePlayer('A'),kicker],comparison_players:[enginePlayer('A')]}}));
  assert.match(html,/W6.*W7.*W8/s);
  assert.match(html,/12\.0/);
  assert.match(html,/K\/DEF not modeled/);
  assert.doesNotMatch(html,/>0\.0</);
  assert.match(html,/team-average environment/);
});
test('player profile never substitutes a missing player and labels engine research',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const charts=loadComponent('src/components/OutcomeCharts.tsx',{'@/lib/workspace':lib});
  const startsit=loadComponent('src/components/WorkspaceStartSit.tsx',{'@/lib/workspace':lib,'./OutcomeCharts':charts});
  const {WorkspacePlayerProfile}=loadComponent('src/components/WorkspacePlayerProfile.tsx',{'@/lib/workspace':lib,'./OutcomeCharts':charts,'./WorkspaceStartSit':startsit});
  const overview={league_id:'a',week:6,roster_players:[],comparison_players:[enginePlayer('A',{game_log:[{week:4,points:21.5}]})],
    outcomes:{player_ranges:{A:{density:Array(27).fill(1/27),mean:10,p10:3,p50:9,p90:19,boom_probability:.1,bust_probability:.3,basis:'provider'}}}};
  assert.match(renderToStaticMarkup(React.createElement(WorkspacePlayerProfile,{overview,playerId:'missing'})),/not in this snapshot/);
  const html=renderToStaticMarkup(React.createElement(WorkspacePlayerProfile,{overview,playerId:'A'}));
  assert.match(html,/Engine rest of season/);
  assert.match(html,/5 games · 1 with market lines/);
  assert.match(html,/Research · if playing/);
  assert.match(html,/21\.5/);
  assert.match(html,/Projected/);
  assert.match(html,/Boom ≥20/);
  assert.match(html,/<svg[^>]*role="img"/);
});
test('waiver guidance fails closed and shows tiers, lineup gains and waiver priority',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const {WorkspaceEngineWaivers}=loadComponent('src/components/WorkspaceEngineWaivers.tsx',{'@/lib/workspace':lib});
  const base={waiver_type:'rolling',waiver_position:6,teams:12,waiver_clear_days:2,tier_rule:'rule',trending:[]};
  const closed=renderToStaticMarkup(React.createElement(WorkspaceEngineWaivers,{overview:{league_id:'a',engine_waivers:{...base,status:'owner_roster_unresolved',rows:[]}}}));
  assert.match(closed,/No waiver guidance for this snapshot \(owner roster unresolved\)/);
  const html=renderToStaticMarkup(React.createElement(WorkspaceEngineWaivers,{overview:{league_id:'a',engine_waivers:{...base,status:'research',rows:[
    {add:enginePlayer('FA'),compare:enginePlayer('Mine'),ros_gain:16,week:6,week_gain:-2,tier:'priority',reasons:['why']},
    {add:enginePlayer('K2',{position:'K',engine_ros_points:null}),compare:enginePlayer('K1'),ros_gain:null,week:null,week_gain:3.5,tier:'stream',reasons:['k']}]}}}));
  assert.match(html,/your priority 6 of 12/);
  assert.match(html,/Priority/); assert.match(html,/\+16\.0/); assert.match(html,/-2\.0/); assert.match(html,/Stream/);
  assert.match(html,/drop Mine/);
  assert.doesNotMatch(html,/Trending adds/);
  const hot=renderToStaticMarkup(React.createElement(WorkspaceEngineWaivers,{overview:{league_id:'a',engine_waivers:{...base,status:'research',rows:[],trending:[{player:enginePlayer('Riser'),adds:5400}]}}}));
  assert.match(hot,/Trending adds on Sleeper/); assert.match(hot,/\+5,400/); assert.match(hot,/does not change the guidance/);
});
test('start/sit withholds win probability with a reason and draws curves only from simulated ranges',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const charts=loadComponent('src/components/OutcomeCharts.tsx',{'@/lib/workspace':lib});
  const {WorkspaceStartSit}=loadComponent('src/components/WorkspaceStartSit.tsx',{'@/lib/workspace':lib,'./OutcomeCharts':charts});
  const withheld={league_id:'a',week:6,roster_players:[enginePlayer('A'),enginePlayer('B')],
    outcomes:{status:'withheld',reason:'starter_blockers',blockers:['X: game in progress'],player_ranges:{},best_changes:[]}};
  const html=renderToStaticMarkup(React.createElement(WorkspaceStartSit,{overview:withheld}));
  assert.match(html,/Withheld: starter blockers — X: game in progress/);
  assert.match(html,/No simulated distribution/);
  assert.doesNotMatch(html,/% of simulations/);
  const range={density:Array(27).fill(1/27),mean:12,p10:4,p50:11,p90:22,boom_probability:.2,bust_probability:.2,basis:'provider'};
  const ready={...withheld,outcomes:{status:'estimated_research',reason:'r',blockers:[],win_probability:.42,best_win_probability:.48,
    best_changes:[{slot:'WR',start:'B',start_name:'B',replaces:'A',replaces_name:'A'}],player_ranges:{A:range,B:{...range,mean:14}},
    validation_matchups:24,validation_brier:.22,coin_flip_brier:.25,blend_status:'provider_only'}};
  const out=renderToStaticMarkup(React.createElement(WorkspaceStartSit,{overview:ready}));
  assert.match(out,/42%/); assert.match(out,/48%/); assert.match(out,/start <a[^>]*>B<\/a> over A/);
  assert.match(out,/not validation/); assert.match(out,/is not applied/);
});
test('markets summary separates actionable from research signals and reports outages',async()=>{
  const sig=(id,actionable,ev,reason)=>({id,sport:'nfl',market:'moneyline',selection:id,bookmaker:'pinnacle',price_american:-110,
    model_probability:.6,fair_probability:.5,ev_percent:ev,actionable,exclusion_reason:reason,matchup:'A @ B',game_time:'2099-01-01T00:00:00Z'});
  const load=(api)=>loadComponent('src/components/WorkspaceMarkets.tsx',{'@/lib/fantasy-api':{fantasyApi:api}});
  const down=load(async()=>null);
  assert.match(renderToStaticMarkup(await down.WorkspaceMarkets()),/connection error, not an empty board/);
  const up=load(async path=>path.startsWith('/signals?sport=nfl')?[sig('Research',false,26,'missing_version_bound_validation'),sig('Real',true,3,null)]
    :path.startsWith('/signals')?[]:path==='/api/v1/ledger'?{scope:'s',items:[],event_count:0,exposure:{}}:{narrative:'none'});
  const html=renderToStaticMarkup(await up.WorkspaceMarkets());
  assert.ok(html.indexOf('>Real<')<html.indexOf('>Research<'),'actionable rows first');
  assert.match(html,/Research · missing version bound validation/);
  assert.match(html,/not an edge/);
});

test('trade outlook shows value bars, position tiles and never zero-fills missing research',()=>{
  const helpers=loadComponent('src/lib/workspace.ts');
  const {WorkspaceTradeOutlook}=loadComponent('src/components/WorkspaceTradeOutlook.tsx',{'@/lib/workspace':helpers});
  const side=(team,gain,pos)=>({team,status:'research',weeks:2,lineup_gain:gain,by_position:pos,weekly:[{week:6,gain:gain/2},{week:7,gain:gain/2}],unmodeled_players:[]});
  const players=[{player_id:'a',name:'Alpha',position:'RB'},{player_id:'b',name:'Bravo',position:'WR'}];
  const outlook={status:'research',side_a:side('Mine',12,{QB:0,RB:-8,WR:20,TE:0}),side_b:side('Theirs',-12,{QB:0,RB:8,WR:-20,TE:0}),player_ros_points:{a:80,b:95},note:'Engine research note.'};
  const html=renderToStaticMarkup(React.createElement(WorkspaceTradeOutlook,{outlook,a:['a'],b:['b'],players}));
  assert.match(html,/Mine gains more starting-lineup points/);
  assert.match(html,/\+20\.0/);
  assert.match(html,/-8\.0/);
  assert.match(html,/Week 6 \+6\.0/);
  assert.match(html,/Engine research note/);
  const missing=renderToStaticMarkup(React.createElement(WorkspaceTradeOutlook,{outlook:{...outlook,player_ros_points:{a:null,b:95},side_b:{team:'Theirs',status:'insufficient_engine_research',by_position:{},weekly:[],unmodeled_players:[]}},a:['a'],b:['b'],players}));
  assert.match(missing,/no package total/);
  assert.match(missing,/insufficient engine research\. Missing is not zero/);
  assert.match(missing,/One side has no engine outlook/);
  const off=renderToStaticMarkup(React.createElement(WorkspaceTradeOutlook,{outlook:{status:'rosters_unresolved',player_ros_points:{}},a:[],b:[],players}));
  assert.match(off,/outlook unavailable \(rosters unresolved\)/);
});

test('full-tool routes stay inside their workspace in the shell',()=>{
  const {routeWorkspace}=loadComponent('src/lib/workspace.ts');
  assert.equal(routeWorkspace('/ledger'),'markets');
  assert.equal(routeWorkspace('/parlays'),'markets');
  assert.equal(routeWorkspace('/calibration/props'),'research');
  assert.equal(routeWorkspace('/fantasy/models'),'research');
  assert.equal(routeWorkspace('/operations'),'settings');
  assert.equal(routeWorkspace('/'),'today');
});

test('native research and settings views fail closed and never certify health or promotion',async()=>{
  const helpers=loadComponent('src/lib/workspace.ts');
  const track=(name,weeks)=>({name,status:'prospective_research',graded_weeks:weeks,required_weeks:6,eligible_for_owner_review:false,serving_promoted:false,blockers:['needs_6_graded_weeks_has_'+weeks],engine_forecasts:36,statuses:{},pool:{n:0,weeks:[],engine_mae:null,sleeper_mae:null,paired_difference:null,ci:null}});
  const live={'/api/v2/fantasy/engine-qualification':{tracks:[track('Projection engine v1',2)],note:'Pairing note.',win_probability:{status:'prospective_research',captured_matchups:3,graded:1,brier:0.09,coin_flip_brier:0.25,log_loss:0.3,statuses:{graded:1,awaiting_final_week:2}}},
    '/calibration':{reports:[{sport:'nfl',market:'spread',sample_size:284,brier_score:0.267,passed_gate:false,evaluated_at:'x'}]},
    '/calibration/evaluation-status':{status:'current',operationally_fresh:true},
    '/experiments/nfl-predictor/governance':{status:'review_available',review:{forecast_count:46}},
    '/operations/history':{status:'current',alerts:['disk_space_low'],latest:{at:'2026-10-12T21:00:00Z',performance:{peak_rss_bytes:87511040}}},
    '/calibration/odds-status':{configured:true,quota_blocked:false,quota_floor:10,telemetry:{remaining:12},sports:[{sport:'nfl',reason:'outside_refresh_window'}]},
    '/calibration/prop-provider-status':{enabled:true,providers:{sgo:{configured:true,daily_limit:100,reserved_today:25,unit:'requests',blocked_seconds:0}}}};
  const api=(data)=>({fantasyApi:async(path)=>data[path]??null});
  const render=async(file,name,data)=>{const mod=loadComponent(file,{'@/lib/fantasy-api':api(data),'@/lib/workspace':helpers});return renderToStaticMarkup(await mod[name]());};
  const research=await render('src/components/WorkspaceResearch.tsx','WorkspaceResearch',live);
  assert.match(research,/2 \/ 6/);
  assert.match(research,/Not promoted/);
  assert.match(research,/needs 6 graded weeks has 2/);
  assert.match(research,/0 \/ 1/);
  assert.match(research,/awaiting final week: 2/);
  assert.match(research,/0\.090/);
  const settings=await render('src/components/WorkspaceSettings.tsx','WorkspaceSettings',live);
  assert.match(settings,/disk_space_low/);
  assert.match(settings,/25 \/ 100 requests/);
  assert.match(settings,/outside refresh window/);
  const down=await render('src/components/WorkspaceSettings.tsx','WorkspaceSettings',{});
  assert.match(down,/not a clean bill of health/);
  const downResearch=await render('src/components/WorkspaceResearch.tsx','WorkspaceResearch',{});
  assert.match(downResearch,/connection error, not a failed model/);
});
