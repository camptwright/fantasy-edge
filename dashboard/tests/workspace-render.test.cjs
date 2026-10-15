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
  }).outputText,{exports:target.exports,URLSearchParams,require:id=> {
    if (overrides[id]) return overrides[id];
    if (id === '@/lib/availability') return loadComponent('src/lib/availability.ts');
    if (id === './WorkspaceLateSwap') return loadComponent('src/components/WorkspaceLateSwap.tsx', overrides);
    if (id === './WorkspaceDynastyControls') return loadComponent('src/components/WorkspaceDynastyControls.tsx', overrides);
    if (id === './WorkspaceRoleChanges') return loadComponent('src/components/WorkspaceRoleChanges.tsx', overrides);
    return require(id);
  }});
  return target.exports;
}
test('availability holds and unfamiliar restrictions show review rather than green clearance',()=>{
  const {verdict}=loadComponent('src/components/WorkspaceAreTheyPlaying.tsx',{'@/lib/workspace':loadComponent('src/lib/workspace.ts')});
  const held=verdict({injury_status:'Q',game_availability_hold:true,week_game_status:'scheduled'});
  assert.equal(held.label,'Review');assert.equal(held.tone,'warn');
  const unknown=verdict({injury_status:'PROVIDER_NEW_RESTRICTION',week_game_status:'scheduled'});
  assert.equal(unknown.label,'Review');assert.equal(unknown.tone,'warn');
});
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
    '@/components/SnapshotWindow':{SnapshotWindow:({children})=>children,SnapshotRetry:()=>null},
    '@/components/WorkspaceTradeOutlook':{WorkspaceTradeOutlook:()=>React.createElement('div')},
  });
  const html=renderToStaticMarkup(React.createElement(WorkspaceTrade,{overview:{league_id:'a',generated_at:'now',comparison_players:[]}}));
  assert.doesNotMatch(html,/aria-label="(?:Add|Drop) Player/);
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
  const startsit=loadComponent('src/components/WorkspaceStartSit.tsx',{'@/lib/workspace':lib,'./OutcomeCharts':charts,'./WorkspaceAreTheyPlaying':loadComponent('src/components/WorkspaceAreTheyPlaying.tsx',{'@/lib/workspace':lib})});
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
  const charts=loadComponent('src/components/OutcomeCharts.tsx',{'@/lib/workspace':lib});
  const {WorkspaceEngineWaivers}=loadComponent('src/components/WorkspaceEngineWaivers.tsx',{'@/lib/workspace':lib,'./OutcomeCharts':charts});
  const base={waiver_type:'rolling',waiver_position:6,teams:12,waiver_clear_days:2,tier_rule:'rule',trending:[]};
  const closed=renderToStaticMarkup(React.createElement(WorkspaceEngineWaivers,{overview:{league_id:'a',engine_waivers:{...base,status:'owner_roster_unresolved',rows:[]}}}));
  assert.match(closed,/No waiver guidance for this snapshot \(owner roster unresolved\)/);
  const html=renderToStaticMarkup(React.createElement(WorkspaceEngineWaivers,{overview:{league_id:'a',engine_waivers:{...base,status:'research',horizon_weeks:3,
    thresholds:{min_lineup_gain:1,min_stream_gain:1},rows:[
    {add:enginePlayer('FA',{sos_ros_stars:4,sos_next4_stars:null}),compare:enginePlayer('Mine'),ros_gain:16,week:6,week_gain:-2,tier:'priority',reasons:['why'],
      weekly:[{week:6,gain:-2},{week:7,gain:18,add_status:'verified_bye'}],alternative_drops:[{drop_id:'other',name:'Other Drop',lineup_gain:12}],needed_by_week:7},
    {add:enginePlayer('K2',{position:'K',engine_ros_points:null}),compare:enginePlayer('K1'),ros_gain:null,week:null,week_gain:3.5,tier:'stream',reasons:['k']}]}}}));
  assert.match(html,/your priority 6 of 12/);
  assert.match(html,/Priority/); assert.match(html,/\+16\.0/); assert.match(html,/-2\.0/); assert.match(html,/Stream/);
  assert.match(html,/drop Mine/);
  assert.match(html,/Schedule ROS: 4 of 5 stars/); assert.match(html,/Next 4 —/);
  assert.match(html,/3-week lineup gain/); assert.match(html,/horizon=4/);
  assert.match(html,/Minimum improvement: 1\.0 lineup pts/); assert.match(html,/Other Drop/);
  assert.match(html,/Useful by Week 7/); assert.match(html,/Compare other drops/);
  assert.doesNotMatch(html,/Trending adds/);
  const hot=renderToStaticMarkup(React.createElement(WorkspaceEngineWaivers,{overview:{league_id:'a',engine_waivers:{...base,status:'research',rows:[],trending:[{player:enginePlayer('Riser'),adds:5400}]}}}));
  assert.match(hot,/Trending adds on Sleeper/); assert.match(hot,/\+5,400/); assert.match(hot,/does not change the guidance/);
  const partial=renderToStaticMarkup(React.createElement(WorkspaceEngineWaivers,{overview:{league_id:'a',engine_waivers:{...base,
    status:'incomplete_coverage',coverage_blockers:[{week:7,missing_player_ids:['secret-id'],missing_players:[{name:'Missing WR',position:'WR'}]}],
    rows:[{add:enginePlayer('Stream K',{position:'K'}),compare:enginePlayer('K1'),ros_gain:null,week:6,week_gain:2,tier:'stream',reasons:[]}]}}}));
  assert.match(partial,/Add Stream K/); assert.match(partial,/Week 7: WR: Missing WR/);
  assert.doesNotMatch(partial,/secret-id/);
});
test('start/sit withholds win probability with a reason and draws curves only from simulated ranges',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const charts=loadComponent('src/components/OutcomeCharts.tsx',{'@/lib/workspace':lib});
  const {WorkspaceStartSit}=loadComponent('src/components/WorkspaceStartSit.tsx',{'@/lib/workspace':lib,'./OutcomeCharts':charts,'./WorkspaceAreTheyPlaying':loadComponent('src/components/WorkspaceAreTheyPlaying.tsx',{'@/lib/workspace':lib})});
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
  assert.equal(routeWorkspace('/parlays'),'props');
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

test('game projections label research and fail closed',()=>{
  const {GameProjections}=loadComponent('src/components/WorkspaceMarkets.tsx',{'@/lib/fantasy-api':{fantasyApi:async()=>null}});
  assert.match(renderToStaticMarkup(React.createElement(GameProjections,{data:null})),/service error, not an empty slate/);
  const data={status:'research',ratings:[{team:'SEA',rating:5.4},{team:'NYJ',rating:-6.1}],games:[
    {game_id:'g',home:'IND',away:'TEN',game_time:'2026-10-18T17:00:00Z',model_margin:9.7,market_margin:7,margin:7.4,home_win_probability:.72,market_weight:.85}],
    evidence:{test_seasons:[2015,2025],model_brier:.2212,previous_elo_brier:.2326,market_brier:.2128,regressed_brier:.2135}};
  const html=renderToStaticMarkup(React.createElement(GameProjections,{data}));
  assert.match(html,/IND −9\.7/); assert.match(html,/IND −7\.0/); assert.match(html,/model keeps 15% of its view/);
  assert.match(html,/0\.2212 vs 0\.2326/); assert.match(html,/\+5\.4/); assert.match(html,/-6\.1/);
});

test('trade market row shows FantasyCalc totals or its status',()=>{
  const helpers=loadComponent('src/lib/workspace.ts');
  const {WorkspaceTradeOutlook}=loadComponent('src/components/WorkspaceTradeOutlook.tsx',{'@/lib/workspace':helpers});
  const side=(team,gain)=>({team,status:'research',weeks:1,lineup_gain:gain,by_position:{QB:0,RB:0,WR:gain,TE:0},weekly:[{week:6,gain}],unmodeled_players:[]});
  const outlook=(market)=>({status:'research',side_a:side('Mine',4),side_b:side('Theirs',-4),player_ros_points:{a:10,b:12},note:'n',market});
  const players=[{player_id:'a',name:'A',position:'WR'},{player_id:'b',name:'B',position:'WR'}];
  const seen=renderToStaticMarkup(React.createElement(WorkspaceTradeOutlook,{outlook:outlook({status:'observed',values:{a:4200,b:6100},side_a_total:4200,side_b_total:6100,note:'Index note.'}),a:['a'],b:['b'],players}));
  assert.match(seen,/Mine gives 4,200 · Theirs gives 6,100/); assert.match(seen,/favours Mine receiving 1,900 more/); assert.match(seen,/Index note/);
  const stale=renderToStaticMarkup(React.createElement(WorkspaceTradeOutlook,{outlook:outlook({status:'stale',values:{}}),a:['a'],b:['b'],players}));
  assert.match(stale,/Trade market value unavailable \(stale\)/);
});

test('all-leagues view summarises each league and players rostered in several',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const {WorkspaceAllLeagues}=loadComponent('src/components/WorkspaceAllLeagues.tsx',{'@/lib/workspace':lib});
  const player=(id,name)=>({player_id:id,name,position:'WR',team:'DET',points:12,consensus_week_points:14.2,injury_status:null});
  const ov=(starters)=>({status:'snapshot_available',week:6,matchup:{mine:{name:'Mine',recorded_points:0,starters:starters.map(id=>({player_id:id}))},opponent:{name:'Them',recorded_points:0}},
    outcomes:{status:'estimated_research',win_probability:.43,reason:'r'},engine_waivers:{rows:[{add:{name:'Add'},compare:{name:'Drop'},ros_gain:12.5}]},
    roster_players:[player('x','Amon-Ra St. Brown')],lineup_changes:{status:'available',start:[],reason:'ok'},waivers:{moves:[]}});
  const html=renderToStaticMarkup(React.createElement(WorkspaceAllLeagues,{items:[
    {league:{league_id:'1',name:'League One',platform:'sleeper'},overview:ov(['x'])},
    {league:{league_id:'2',name:'League Two',platform:'espn'},overview:ov([])},
    {league:{league_id:'3',name:'League Three',platform:'sleeper'},overview:null}]}));
  assert.match(html,/43% to win/); assert.match(html,/Best add.*Add/); assert.match(html,/\+12\.5/);
  assert.match(html,/Snapshot not ready.*Not an empty league/);
  assert.match(html,/Amon-Ra St\. Brown/); assert.match(html,/League One · starting/); assert.match(html,/League Two · bench/);
});

test('trade finder shows both gains, market context and fails closed',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const {WorkspaceTradeIdeas}=loadComponent('src/components/WorkspaceTradeIdeas.tsx',{'@/lib/workspace':lib});
  assert.match(renderToStaticMarkup(React.createElement(WorkspaceTradeIdeas,{ideas:null,league:'a'})),/service error, not a lack of trades/);
  const pl=(id,name,pos)=>({player_id:id,name,position:pos,engine_ros_points:100});
  const ideas={status:'research',mutual_trades:7,note:'Nothing is proposed.',rows:[{give:pl('q','Bo Nix','QB'),get:pl('w','Joe Burrow','QB'),partner:'Bite Club',my_gain:25.5,their_gain:13.7,weeks:12,give_market_value:3000,get_market_value:5200}]};
  const html=renderToStaticMarkup(React.createElement(WorkspaceTradeIdeas,{ideas,league:'a'}));
  assert.match(html,/7 trades help both lineups/); assert.match(html,/Give.*Bo Nix/); assert.match(html,/Get.*Joe Burrow/);
  assert.match(html,/\+25\.5 pts/); assert.match(html,/\+13\.7 pts/); assert.match(html,/values Joe Burrow 2,200 higher/);
  const none=renderToStaticMarkup(React.createElement(WorkspaceTradeIdeas,{ideas:{...ideas,rows:[]},league:'a'}));
  assert.match(none,/No one-for-one trade improves both/);
});

test('position ladder ranks yours and available together and skips other rosters',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const {WorkspacePositionLadder}=loadComponent('src/components/WorkspacePositionLadder.tsx',{'@/lib/workspace':lib});
  const pl=(id,name,own,ros)=>({player_id:id,name,position:'WR',ownership:own,engine_ros_points:ros,consensus_week_points:null,engine_week_points:ros/10,points:null});
  const overview={league_id:'a',week:6,strength:{positions:[{position:'WR',rank:1,teams:12}]},comparison_players:[
    pl('o','Other Star','other_roster',150),pl('m','My Guy','your_roster',120),pl('f','Free Agent','unrostered_snapshot',130),pl('x','Deep Cut','unrostered_snapshot',40)]};
  const html=renderToStaticMarkup(React.createElement(WorkspacePositionLadder,{overview}));
  assert.match(html,/Your rank 1 of 12/);
  assert.match(html,/WR2.*Free Agent.*Available/); assert.match(html,/WR3.*My Guy.*Yours/);
  assert.doesNotMatch(html,/Other Star/);
  assert.match(html,/No ranked players/); // QB/RB/TE columns have no research
});

test('matchup board pairs slots, colours results against projection and reports accuracy',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const {WorkspaceMatchupBoard}=loadComponent('src/components/WorkspaceMatchupBoard.tsx',{'@/lib/workspace':lib});
  const st=(slot,id,name,points,recorded)=>({slot,player_id:id,name,points,recorded_points:recorded,source:'estimated',locked:true,position:slot});
  const mine={name:'Mine',recorded_points:127.8,starters:[st('QB','a','Jacoby Brissett',19.2,31.3),st('TE','b','T.J. Hockenson',10.4,1.7)],optimal:[st('QB','a','Jacoby Brissett',19.2,31.3)],optimal_points:150,start_sit_accuracy:.852};
  const opp={name:'Them',recorded_points:213.8,starters:[st('QB','c','Drake Maye',18.8,47.5)],optimal:[],optimal_points:null,start_sit_accuracy:null};
  const html=renderToStaticMarkup(React.createElement(WorkspaceMatchupBoard,{mine,opponent:opp,league:'L',season:[{week:1,actual:120,optimal:140,accuracy:.857},{week:2,actual:100,optimal:100,accuracy:1}]}));
  assert.match(html,/Jacoby Brissett.*31\.3/); assert.match(html,/text-emerald-300">19\.2/); assert.match(html,/text-rose-300">10\.4/);
  assert.match(html,/Drake Maye/); assert.match(html,/85%/); assert.match(html,/Season average.*93%/); assert.match(html,/20\.0/);
});

test('season tiles and standings show record, odds and the playoff line',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const {SeasonTiles,WorkspaceStandings}=loadComponent('src/components/WorkspaceStandings.tsx',{'@/lib/workspace':lib});
  const row=(id,name,w,l,pf,odds,mine=false)=>({roster_id:id,name,is_mine:mine,wins:w,losses:l,ties:0,points_for:pf,points_against:500,playoff_odds:odds,first_seed_odds:odds/3,projected_wins:w+4});
  const standings={status:'research',week:6,playoff_teams:2,remaining_games:40,simulations:10000,note:'Research.',rows:[row('2','Transfer Portal',5,0,800,.99),row('1','Tel Aviv Ted',4,1,780,.97,true),row('3','Bite Club',1,4,500,.05)]};
  const tiles=renderToStaticMarkup(React.createElement(SeasonTiles,{standings}));
  assert.match(tiles,/2nd/); assert.match(tiles,/4–1/); assert.match(tiles,/156\.0/); assert.match(tiles,/97%/); assert.match(tiles,/Top 2/);
  const table=renderToStaticMarkup(React.createElement(WorkspaceStandings,{standings}));
  assert.match(table,/Tel Aviv Ted.*You/); assert.match(table,/10,000 simulated seasons/);
  assert.equal(renderToStaticMarkup(React.createElement(SeasonTiles,{standings:{...standings,status:'updating'}})),'');
});

test('are they playing puts byes and outs first and never calls no designation a clearance',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const {WorkspaceAreTheyPlaying,verdict}=loadComponent('src/components/WorkspaceAreTheyPlaying.tsx',{'@/lib/workspace':lib});
  const pl=(id,name,extra)=>({player_id:id,name,position:'WR',team:'DET',injury_status:null,locked:false,game_availability_hold:false,week_game_status:'scheduled',week_kickoff:'2026-10-18T17:00:00Z',opponent:'GB',...extra});
  const players=[pl('a','Healthy'),pl('b','Hockenson',{week_game_status:'no_game_this_week'}),pl('c','Flowers',{injury_status:'Questionable'}),pl('d','Hurt',{injury_status:'Out'})];
  assert.equal(verdict(players[0]).label,'Scheduled'); assert.equal(verdict(players[1]).label,'Bye'); assert.equal(verdict(players[3]).label,'Out');
  assert.equal(verdict(pl('ir','Reserve',{injury_status:'INJURY_RESERVE'})).label,'IR');
  const html=renderToStaticMarkup(React.createElement(WorkspaceAreTheyPlaying,{overview:{league_id:'L',roster_players:players,matchup:{mine:{starters:players.map((p,i)=>({slot:['WR','WR','FLEX','TE'][i],player_id:p.player_id}))}}}}));
  assert.match(html,/2 starters need a replacement plan/);
  assert.ok(html.indexOf('Hockenson')<html.indexOf('Healthy') && html.indexOf('Hurt')<html.indexOf('Flowers'));
  assert.match(html,/participation unconfirmed/);
  // A modelled designation shows the historical play rate and practice participation.
  const odds=verdict(pl('e','Limited',{injury_status:'Questionable',play_probability:0.78,practice_status:'limited'}));
  assert.equal(odds.label,'Q · 78%'); assert.match(odds.detail,/^Limited practice · regulars listed Questionable on the final report played 78%\. Check news/);
  assert.equal(verdict(players[2]).label,'Questionable');  // not modelled: no number invented
});

test('late swap renders roster contingency and dated check time without a transaction control',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const {WorkspaceLateSwap}=loadComponent('src/components/WorkspaceLateSwap.tsx',{'@/lib/workspace':lib});
  const html=renderToStaticMarkup(React.createElement(WorkspaceLateSwap,{overview:{league_id:'L',roster_players:[],late_swap:{
    plans:[{starter_id:'a',starter_name:'Questionable Starter',slot:'WR',replacement_id:'b',replacement_name:'Later Backup',replacement_points:12,
      check_by:'2026-10-18T17:00:00Z',replacement_kickoff:'2026-10-18T20:00:00Z',risk_adjusted_points:17.6}],blockers:[]}}}));
  assert.match(html,/Later Backup/); assert.match(html,/conditional plan value/); assert.match(html,/one absence/);
  assert.doesNotMatch(html,/<button|<form/);
});

test('league analyzer lists team scores and slot ranks',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const {WorkspaceLeagueAnalyzer}=loadComponent('src/components/WorkspaceLeagueAnalyzer.tsx',{'@/lib/workspace':lib});
  const overview={strength:{status:'research',teams:12,team_rankings:[{roster_id:'2',name:'Transfer Portal',score:100,rank:1},{roster_id:'1',name:'Tel Aviv Ted',score:96,rank:2,is_mine:true}],
    slots:[{slot:'QB',player_name:'Bo Nix',value:180,rank:12,teams:12},{slot:'RB1',player_name:'Kenneth Walker',value:150,rank:3,teams:12},{slot:'BENCH',player_name:null,value:200,rank:12,teams:12}]}};
  const html=renderToStaticMarkup(React.createElement(WorkspaceLeagueAnalyzer,{overview}));
  assert.match(html,/Transfer Portal.*100/); assert.match(html,/Tel Aviv Ted.*You.*96/);
  assert.match(html,/Bo Nix.*12th/); assert.match(html,/Kenneth Walker.*3rd/); assert.match(html,/Top bench players.*12th/);
  assert.match(html,/bg-rose-400/); assert.match(html,/bg-emerald-400/);
});

test('post-game recap shows result, all-play, bench and the median chart',()=>{
  const lib=loadComponent('src/lib/workspace.ts');
  const {WorkspaceRecap}=loadComponent('src/components/WorkspaceRecap.tsx',{'@/lib/workspace':lib});
  const g={home:'A',away:'B',home_points:150,away_points:90};
  const recap={status:'available',completed_weeks:[1,2,3],note:'n',week:{week:3,points:135.2,opponent:'Bite Club',opponent_points:120,result:'W',league_median:118,score_rank:3,teams:12,all_play_wins:9,all_play_losses:2,
    top_scorer:'Jaxon Smith-Njigba',top_scorer_points:28.4,best_bench:'Rachaad White',best_bench_points:17,bench_points_left:13.8,high_score:g,closest_game:g,biggest_blowout:g,low_team:'Jack',low_points:70},
    season:{weeks:[1,2,3],my_points:[188,146,135],median_points:[140,130,118],all_play_wins:28,all_play_losses:5,wins:3,expected_wins:2.55,luck:.45}};
  const html=renderToStaticMarkup(React.createElement(WorkspaceRecap,{recap,league:'L'}));
  assert.match(html,/Win · 135\.2 – 120\.0 vs Bite Club/); assert.match(html,/9–2/); assert.match(html,/\+17\.2 for you/);
  assert.match(html,/Rachaad White/); assert.match(html,/\+0\.5 wins/); assert.match(html,/<svg/); assert.match(html,/week=2/);
  assert.match(renderToStaticMarkup(React.createElement(WorkspaceRecap,{recap:{status:'no_completed_weeks',completed_weeks:[],season:{}},league:'L'})),/No recap yet/);
});

const propRow=(over={})=>({key:'p:g:receptions',sport:'nfl',game_id:'g',game_time:'2026-10-18T17:00:00Z',matchup:'BUF @ KC',player_id:'p',player:'Wide One',
  position:'WR',team:'KC',opponent:'BUF',stat:'receptions',line:4.5,books:4,quoted:5,fair_over:.55,spread:.03,hold:.045,
  best_over:{book:'draftkings',price:110},best_under:{book:'fanduel',price:-130},ev_over:.155,ev_under:-.1,other_lines:[5.5],
  hit:{l5:{hits:4,games:5},l10:{hits:7,games:10},season:{hits:3,games:5},vs_opponent:null,average_l10:5.2,last5:[6,5,7,3,5]},
  engine:null,dvp:{rank:3,teams:32},offers:[{book:'draftkings',line:4.5,over:110,under:-135,observed_at:'x'}],last_seen:'x',score:.15,...over});

test('prop helpers sort and filter the board by value, trend and matchup',()=>{
  const p=loadComponent('src/lib/props.ts');
  const a=propRow(), b=propRow({key:'b',player:'Back Up',ev_over:-.03,ev_under:.01,hit:{...a.hit,l10:{hits:2,games:10}},dvp:{rank:30,teams:32}});
  assert.equal(p.bestSide(a),'over'); assert.equal(p.bestSide(b),'under');
  assert.equal(p.sortRows([b,a],'ev').map(r=>r.key).join(),'p:g:receptions,b');
  // b's best side is the under, which went 8/10; a's over went 7/10.
  assert.equal(p.sortRows([a,b],'l10').map(r=>r.key).join(),'b,p:g:receptions');
  // An under vs the 30th-ranked (stingy) defence is as good a matchup as an over vs the 3rd (soft); ties go by key.
  assert.equal(p.sortRows([a,b],'dvp').map(r=>r.key).join(),'b,p:g:receptions');
  assert.equal(p.sortRows([a,propRow({key:'c',dvp:{rank:12,teams:32}})],'dvp').map(r=>r.key).join(),'p:g:receptions,c');
  assert.equal(p.filterRows([a,b],{minEv:0.05}).length,1);
  assert.equal(p.filterRows([a,b],{q:'kc'}).length,2);
  assert.equal(p.filterRows([a,b],{book:'fanduel'}).length,0);
  assert.equal(p.american(110),'+110'); assert.equal(p.signedPct(.155),'+15.5%'); assert.equal(p.rate(null),'—');
});

test('prop board renders best prices, EV and trend, and explains an empty board',()=>{
  const helpers=loadComponent('src/lib/props.ts');
  const {PropBoard}=loadComponent('src/components/PropBoard.tsx',{'@/lib/props':helpers});
  const html=renderToStaticMarkup(React.createElement(PropBoard,{board:{status:'research',sport:'nfl',books:['draftkings'],stats:['receptions'],total:1,rows:[propRow()],tracker:null}}));
  assert.match(html,/Wide One/); assert.match(html,/Receptions 4\.5/); assert.match(html,/\+110/); assert.match(html,/DraftKings/);
  assert.match(html,/\+15\.5%/); assert.match(html,/fair 55%/); assert.match(html,/Over L10 70%/); assert.match(html,/D vs Pos 3\/32/); assert.match(html,/alt 5\.5/);
  const empty=renderToStaticMarkup(React.createElement(PropBoard,{board:{status:'research',sport:'nfl',books:[],stats:[],total:0,rows:[],tracker:null}}));
  assert.match(empty,/Books post most NFL props midweek/);
});

test('parlay card shows EV across games and only fair odds for same-game parlays',()=>{
  const helpers=loadComponent('src/lib/props.ts');
  const {ParlayCard}=loadComponent('src/components/ParlayGenerator.tsx',{'@/lib/props':helpers});
  const leg={id:'l',book:'draftkings',price:110,fair:.55,ev:.155,side:'over',line:4.5,stat:'receptions',player:'Wide One',position:'WR',team:'KC',opponent:'BUF',matchup:'BUF @ KC',game_time:'x',reasons:['+15.5% vs 4-book no-vig consensus (55% fair)']};
  const cross=renderToStaticMarkup(React.createElement(ParlayCard,{index:0,parlay:{book:'draftkings',legs:[leg,{...leg,id:'m',player:'Two'}],decimal:4.41,american:341,independent_probability:.3025,probability:.3025,fair_american:231,same_game:false,ev:.334,score:1}}));
  assert.match(cross,/Best · DraftKings/); assert.match(cross,/\+341/); assert.match(cross,/30\.3%/); assert.match(cross,/\+33\.4%/); assert.match(cross,/no-vig consensus/);
  assert.doesNotMatch(cross,/if independent/);
  const sgp=renderToStaticMarkup(React.createElement(ParlayCard,{index:1,parlay:{book:'draftkings',legs:[leg,{...leg,id:'n',stat:'receiving_yards'}],decimal:4.41,american:341,independent_probability:.3025,probability:.41,fair_american:144,same_game:true,ev:null,score:1}}));
  assert.match(sgp,/Price to beat/); assert.match(sgp,/30\.3% if independent/); assert.match(sgp,/longer than \+144/); assert.doesNotMatch(sgp,/>EV</);
});
