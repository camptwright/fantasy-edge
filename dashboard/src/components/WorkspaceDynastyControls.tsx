"use client";
export type DynastyPick = {side:'a'|'b';season:number;round:number;slot?:number;value?:number;source?:string;original_roster_id?:string};
export type DynastyScenario = {goal:'balanced'|'contender'|'rebuild';picks:DynastyPick[]};
export function WorkspaceDynastyControls({value,onChange,disabled=false,season}:{value:DynastyScenario;onChange:(value:DynastyScenario)=>void;disabled?:boolean;season:number}) {
  function update(index:number,change:Partial<DynastyPick>) {onChange({...value,picks:value.picks.map((p,i)=>i===index?{...p,...change}:p)});}
  const input='min-h-11 rounded-lg border border-slate-700 bg-slate-950 px-2 text-sm';
  return <details className="mt-4 rounded-xl border border-slate-800 p-4"><summary className="cursor-pointer font-medium">Dynasty goals and rookie picks</summary>
    <fieldset disabled={disabled} className="mt-3 space-y-3"><label className="flex flex-wrap items-center gap-3 text-sm">Your goal <select aria-label="Dynasty planning goal" className={input} value={value.goal} onChange={e=>onChange({...value,goal:e.target.value as DynastyScenario['goal']})}><option value="balanced">Balanced</option><option value="contender">Contend now</option><option value="rebuild">Rebuild</option></select></label>
    <p className="text-xs text-slate-400">Add the picks each side gives. Enter values only when you have a price in the same FantasyCalc market-index units. Unpriced picks stay unpriced.</p>
    {value.picks.map((p,i)=><div key={i} className="flex flex-wrap gap-2 rounded-lg bg-slate-950/60 p-3">
      <label className="text-xs">Giving side <select className={`block ${input}`} value={p.side} onChange={e=>update(i,{side:e.target.value as 'a'|'b'})}><option value="a">A</option><option value="b">B</option></select></label>
      <label className="text-xs">Season <input className={`block w-24 ${input}`} type="number" min={season} max={2100} value={p.season} onChange={e=>update(i,{season:Number(e.target.value)})}/></label>
      <label className="text-xs">Round <input className={`block w-20 ${input}`} type="number" min={1} max={10} value={p.round} onChange={e=>update(i,{round:Number(e.target.value)})}/></label>
      <label className="text-xs">Pick slot (optional) <input className={`block w-28 ${input}`} type="number" min={1} max={32} value={p.slot??''} onChange={e=>update(i,{slot:e.target.value===''?undefined:Number(e.target.value)})}/></label>
      <label className="text-xs">Index value (optional) <input className={`block w-32 ${input}`} type="number" min={0} value={p.value??''} onChange={e=>update(i,{value:e.target.value===''?undefined:Number(e.target.value)})}/></label>
      <label className="text-xs">Price source <input className={`block w-40 ${input}`} maxLength={200} value={p.source??''} placeholder="Your scenario or source" onChange={e=>update(i,{source:e.target.value})}/></label>
      <button type="button" className={input} onClick={()=>onChange({...value,picks:value.picks.filter((_,j)=>j!==i)})}>Remove pick</button>
    </div>)}
    <button type="button" disabled={value.picks.length>=12} className={input} onClick={()=>onChange({...value,picks:[...value.picks,{side:'a',season:season+1,round:1}]})}>Add rookie pick</button>
    </fieldset>
  </details>;
}
