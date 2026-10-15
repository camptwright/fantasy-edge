const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');
function load(path,requireModule=require){
  const module={exports:{}};
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,{exports:module.exports,require:requireModule});
  return module.exports;
}
const contract=load('src/lib/workspace-api.generated.ts');
const {hydrateOverview}=load('src/lib/workspace-view.ts',id=>id==='./workspace-api.generated'?contract:require(id));
test('sparse tool response preserves unknowns and restores omitted nested display defaults',()=>{
  const result=hydrateOverview({league_id:'L',status:'snapshot_available',waivers:{status:'withheld'},engine_waivers:{status:'incomplete_coverage'},roster_players:[{player_id:'a',name:'A',points:null}],comparison_players:[]});
  assert.equal(result.waivers.moves.length,0);
  assert.equal(result.engine_waivers.rows.length,0);
  assert.equal(result.roster_players[0].points,null);
  assert.equal(result.roster_players[0].engine_weeks.length,0);
  assert.equal(result.roster_players[0].missing_scoring_keys.length,0);
  assert.equal(result.matchup.mine,null);
  assert.equal(hydrateOverview(null),null);
});
