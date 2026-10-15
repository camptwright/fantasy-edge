type Trend = {recent?:number|null;prior?:number|null;change?:number|null;recent_games?:number;prior_games?:number};
export type RoleChanges = {status:string;trends?:Record<string,Trend>;note?:string|null};
const metrics = [{key:'snap_share',label:'Offensive snap share',percent:true},{key:'targets',label:'Targets / game'},{key:'carries',label:'Carries / game'},{key:'target_share',label:'Target share',percent:true},{key:'carry_share',label:'Carry share',percent:true},{key:'red_zone_targets',label:'Red-zone targets / game'},{key:'red_zone_carries',label:'Red-zone carries / game'}];
export function WorkspaceRoleChanges({profile}:{profile:RoleChanges|null|undefined}) {
  if (!profile) return null;
  const measured=metrics.filter(m=>profile.trends?.[m.key]?.recent!=null);
  function display(v:number|null|undefined,percent?:boolean){return v==null?'Unavailable':percent?`${(v*100).toFixed(1)}%`:v.toFixed(1);}
  return <details className="mt-4 rounded-xl border border-slate-800 p-4"><summary className="cursor-pointer font-medium">Role changes</summary>
    <p className="mt-2 text-xs text-slate-400">Last three games compared with the previous three. Trends require three measured games in each window.</p>
    {measured.length?<dl className="mt-3 space-y-3">{measured.map(m=>{const t=profile.trends![m.key];return <div key={m.key} className="flex flex-wrap justify-between gap-2 text-sm"><dt>{m.label}</dt><dd>{display(t.recent,m.percent)} <span className="text-slate-400">vs {display(t.prior,m.percent)} · {t.change==null?'More history needed':`${t.change>0?'+':''}${display(t.change,m.percent)}`}</span></dd></div>;})}</dl>:<p className="mt-3 text-sm text-slate-400">Measured role history is unavailable for this player.</p>}
    {metrics.some(m=>profile.trends?.[m.key]?.recent==null)&&<p className="mt-3 text-xs text-slate-500">Some usage measurements are unavailable.</p>}
  </details>;
}
