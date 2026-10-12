'use client';
import {useState} from 'react';
import type {PlayerDetail} from '@/lib/workspace-api.generated';

type Valuation={status:string;blockers:string[];surplus?:{low:number;base:number;high:number};interpretation?:string;break_even_keeper_value?:number};
type Result={status:string;players:{player_id:string;status:string;cost_round:number|null;blockers:string[];valuation?:Valuation}[]};
type History={status:string;draft_round?:number;draft_season?:string;draft_id?:string;observed_at?:string;archive?:string;kept_in_draft_season?:boolean|null;same_draft_roster?:boolean};
export function WorkspaceKeeper({league,players}:{league:string;players:PlayerDetail[]}) {
  const [player,setPlayer]=useState(''),[round,setRound]=useState('');
  const [kept,setKept]=useState(''),[drafted,setDrafted]=useState(''),[pick,setPick]=useState('');
  const [result,setResult]=useState<Result|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [history,setHistory]=useState<History|null>(null);
  const [scenario,setScenario]=useState<Record<string,string>>({});
  const requirements=[
    {done:!!player,text:'Choose one current roster player.'},
    {done:!!round&&Number.isInteger(Number(round))&&Number(round)>=1,text:'Confirm the original draft round. Undrafted-player cost needs a commissioner ruling.'},
    {done:kept!=='',text:'Confirm whether the player was already kept in the draft season; a missing provider flag is not “No”.'},
    {done:drafted==='yes',text:'Confirm you originally drafted the player, or obtain the traded-player cost rule.'},
    {done:pick==='yes',text:'Confirm you own the forfeited pick next season; otherwise obtain the unavailable-pick rule.'},
  ];
  if(league!=='1398509004950376448') return <p className="mt-6 text-sm text-slate-400">Keeper rules are not configured for this league. Your one-keeper rules apply to 2016 Warriors.</p>;
  const change=(setter:(v:string)=>void,value:string)=>{setter(value);setResult(null);setError('');};
  function selectPlayer(value:string) {
    setPlayer(value);setRound('');setKept('');setDrafted('');setPick('');setHistory(null);setResult(null);setError('');setScenario({});
  }
  async function loadHistory() {
    setBusy(true);setResult(null);setError('');setHistory(null);
    try {
      const response=await fetch(`/api/workspace/keeper?${new URLSearchParams({league_id:league,player_id:player})}`,{cache:'no-store'});
      if(!response.ok)throw new Error();
      const data:History=await response.json();setHistory(data);
      if(data.status==='archived_draft_pick') {
        setRound(data.draft_round==null?'':String(data.draft_round));
        setKept(data.kept_in_draft_season==null?'':data.kept_in_draft_season?'yes':'no');
        setDrafted('');setPick('');
        setScenario(old=>({...old,draft_season:data.draft_season??'',season:data.draft_season?String(Number(data.draft_season)+1):''}));
      }
    }catch{setError('Archived history unavailable. Manual inputs are not verified history.');}
    finally{setBusy(false);}
  }
  async function review() {
    setBusy(true);setResult(null);setError('');
    const bool=(value:string)=>value===''?null:value==='yes';
    const numeric=(key:string)=>scenario[key]?.trim()?Number(scenario[key]):null;
    const valuation=Object.entries(scenario).some(([key,value])=>!['season','draft_season'].includes(key)&&Boolean(value))?{
      league_id:league,player_id:player,cost_round:round?Number(round)-1:null,
      draft_season:numeric('draft_season'),season:numeric('season'),
      unit:'lineup_points_above_replacement',scoring_basis:scenario.scoring_basis,
      horizon:scenario.horizon,source:scenario.source,
      keeper:{low:numeric('keeper_low'),base:numeric('keeper_base'),high:numeric('keeper_high')},
      pick:{low:numeric('pick_low'),base:numeric('pick_base'),high:numeric('pick_high')},
    }:null;
    try {
      const response=await fetch('/api/workspace/keeper',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({league_id:league,players:[{player_id:player,draft_round:round===''?null:Number(round),kept_last_year:bool(kept),original_drafter:bool(drafted),cost_pick_available:bool(pick),valuation}]})});
      const data=await response.json();
      if(!response.ok || !Array.isArray(data.players)) throw new Error('Keeper review unavailable. Check your inputs and retry.');
      setResult(data);
    } catch {setError('Keeper review unavailable. Check your inputs and retry.');}
    finally {setBusy(false);}
  }
  return <section aria-label="Keeper review" className="mt-6 rounded-xl border border-slate-700 p-4">
    <h3 className="text-lg font-semibold">Keeper eligibility & pick cost</h3>
    <p className="my-3 text-sm text-slate-300">One keeper. No consecutive-year keepers or first-round draftees. Cost is one round earlier: round 6 costs round 5; round 2 costs round 1.</p>
    <p className="mb-4 text-sm text-amber-200">Manual evidence review—not verified draft history or a keeper recommendation. Nothing is saved or submitted. Traded and undrafted player exceptions remain unresolved.</p>
    <details className="mb-4 rounded border border-slate-700 p-3" open><summary className="cursor-pointer font-medium">Required evidence · {requirements.filter(r=>r.done).length}/{requirements.length} supplied</summary><ul className="mt-2 space-y-2 text-sm">{requirements.map(r=><li key={r.text}><span className={r.done?'text-emerald-300':'text-amber-200'}>{r.done?'Supplied':'Needed'}</span> — {r.text}</li>)}</ul><p className="mt-2 text-xs text-slate-400">Supplied is not verified or eligible. First-round draftees and consecutive-year keepers remain ineligible even with every input completed.</p></details>
    <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
      <label>Roster player<select className="mt-1 block min-h-11 w-full rounded bg-slate-900 p-2" value={player} onChange={e=>selectPlayer(e.target.value)}><option value="">Choose a player</option>{players.map(p=><option key={p.player_id} value={p.player_id}>{p.name}</option>)}</select></label>
      <button type="button" disabled={!player || busy} onClick={loadHistory} className="min-h-11 rounded border border-slate-600 px-4 disabled:opacity-50">Load archived draft evidence</button>
      <label>Original draft round<input type="number" min="1" max="100" step="1" className="mt-1 block min-h-11 w-full rounded bg-slate-900 p-2" value={round} onChange={e=>change(setRound,e.target.value)} placeholder="Unknown" /></label>
      {([{label:'Was this player already a keeper in the draft season?',value:kept,set:setKept},{label:'Did you originally draft this player?',value:drafted,set:setDrafted},{label:'Do you own the required cost pick next season?',value:pick,set:setPick}]).map(field=><label key={field.label}>{field.label}<select className="mt-1 block min-h-11 w-full rounded bg-slate-900 p-2" value={field.value} onChange={e=>change(field.set,e.target.value)}><option value="">Unknown</option><option value="yes">Yes</option><option value="no">No</option></select></label>)}
      <details className="sm:col-span-2"><summary className="cursor-pointer py-2">Optional next-season keeper value scenario</summary>
        <p className="my-2 text-sm text-amber-200">Supply keeper and forfeited-pick alternatives in the same league-scored lineup points above replacement, for the same next-season horizon. Do not compare raw QB points to raw RB points, this-season ROS to next-season picks, or trade-value units to points. No market values are invented. This is sensitivity research—not a validated recommendation.</p>
        <div className="grid gap-3 sm:grid-cols-2">{[['draft_season','Original draft season'],['season','Following keeper season'],['scoring_basis','Shared scoring / replacement basis'],['horizon','Shared next-season horizon'],['source','Evidence source / assumptions'],['keeper_low','Keeper low value'],['keeper_base','Keeper base value'],['keeper_high','Keeper high value'],['pick_low','Forfeited pick low value'],['pick_base','Forfeited pick base value'],['pick_high','Forfeited pick high value']].map(([key,label])=><label key={key}>{label}<input type={['scoring_basis','horizon','source'].includes(key)?'text':'number'} step="any" maxLength={500} value={scenario[key]??''} onChange={e=>{setScenario({...scenario,[key]:e.target.value});setResult(null);}} className="mt-1 block min-h-11 w-full rounded bg-slate-900 p-2" placeholder="Not supplied"/></label>)}</div>
      </details>
      <button type="button" disabled={!player || busy} onClick={review} className="min-h-11 rounded border border-emerald-600 px-4 disabled:opacity-50">{busy?'Checking…':'Check eligibility and cost'}</button>
    </fieldset>
    {history&&<div className="mt-3 rounded border border-slate-600 p-3 text-sm"><p>Archive status: {history.status.replaceAll('_',' ')}</p>{history.status==='archived_draft_pick'&&<><p>Draft season {history.draft_season} · Round {history.draft_round} · Draft {history.draft_id}</p><p>Keeper in that draft: {history.kept_in_draft_season==null?'Unknown':history.kept_in_draft_season?'Yes':'No'}. This review is for the following season.</p><p>Observed {history.observed_at ?? 'unknown'} · Archive {history.archive ?? 'unknown'}</p><p>Same draft roster: {history.same_draft_roster?'yes':'no'}. This does not prove continuous ownership or future pick availability. Editable inputs may differ from this archive.</p></>}</div>}
    {error&&<p role="alert" className="mt-3 text-amber-200">{error}</p>}
    {result&&<div role="status" className="mt-4 rounded border border-slate-600 p-3">{result.players.map(p=><div key={p.player_id}><p>{p.status.replaceAll('_',' ')}</p><p>Calculated cost: {p.cost_round==null?'Unknown':`round ${p.cost_round}`} · Cost alone does not establish eligibility or value.</p><ul className="mt-2 list-disc pl-5">{p.blockers.map(b=><li key={b}>{b.replaceAll('_',' ')}</li>)}</ul>{p.valuation&&<div className="mt-3 text-sm"><p>Value scenario: {p.valuation.status.replaceAll('_',' ')}</p>{p.valuation.surplus&&<><p>Keeper minus forfeited pick: {p.valuation.surplus.base.toFixed(1)} lineup points above replacement · sensitivity range {p.valuation.surplus.low.toFixed(1)} to {p.valuation.surplus.high.toFixed(1)}.</p><p>Break-even keeper value: {p.valuation.break_even_keeper_value?.toFixed(1)}. {p.valuation.interpretation?.replaceAll('_',' ')}.</p></>}<ul>{p.valuation.blockers.map(b=><li key={b}>{b.replaceAll('_',' ')}</li>)}</ul></div>}</div>)}<p className="mt-3 text-sm text-slate-400">Supplied scenario only. Sensitivity ranges are not confidence intervals; eligibility remains a separate requirement.</p></div>}
  </section>;
}
