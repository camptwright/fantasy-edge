const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const ts=require('typescript');
const vm=require('node:vm');

function proxy(fetcher,env={FANTASY_API_TOKEN:'private-token',FANTASY_API_URL:'http://production:8000',FANTASY_WORKSPACE_API_URL:'http://readonly:8000'}) {
  const target={exports:{}};
  const code=ts.transpileModule(fs.readFileSync('src/app/api/workspace/decisions/route.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  vm.runInNewContext(code,{exports:target.exports,process:{env},URL,AbortSignal,fetch:fetcher,
    require:id=>id==='next/server'?{NextResponse:{json:(body,options)=>({body,...options})}}:require(id)});
  return target.exports;
}

test('journal writes use production service and keep credentials server-side',async()=>{
  let sent;
  const routes=proxy(async(url,options)=>{sent={url,options};return {status:200,json:async()=>({id:'stored'})};});
  const result=await routes.POST({json:async()=>({league_id:'L',request_id:'uuid',generated_at:'now',action:'pickup',player_ids:['add','drop'],note:'Reason'})});
  assert.equal(result.status,200); assert.equal(result.body.id,'stored');
  assert.match(sent.url,/production:8000\/api\/v2\/personal-fantasy/);
  assert.equal(sent.options.headers.Authorization,'Bearer private-token');
  assert.equal(sent.options.cache,'no-store'); assert.equal(result.headers['Cache-Control'],'no-store');
  assert.doesNotMatch(JSON.stringify(result.body),/private-token/);
});

test('missing credentials and invalid payloads never call the service',async()=>{
  const fail=async()=>{throw new Error('Should not fetch');};
  const noToken=proxy(fail,{});
  assert.equal((await noToken.GET({url:'http://local/api?league=L'})).status,503);
  const routes=proxy(fail);
  assert.equal((await routes.POST({json:async()=>({league_id:'L',action:'trade',player_ids:[]})})).status,400);
});

test('history read is league-scoped and bounded by backend defaults',async()=>{
  let url;
  const routes=proxy(async(value)=>{url=value;return {status:200,json:async()=>({records:[]})};});
  assert.equal((await routes.GET({url:'http://local/api?league=espn%3A123'})).status,200);
  assert.match(url,/leagues\/espn%3A123\/decisions$/);
});
