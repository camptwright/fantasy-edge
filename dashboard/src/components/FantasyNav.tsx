"use client";
import Link from "next/link";
import {useSearchParams} from "next/navigation";

export function FantasyNav(){
 const league=useSearchParams().get('league');
 const links=[['/fantasy','Roster & waivers'],['/fantasy/matchup','Matchup'],
 ['/fantasy/values','Player values & trades'],['/fantasy/models','Model evidence']];
 return <nav aria-label="Fantasy tools" className="mx-auto flex max-w-6xl flex-wrap gap-4 px-5 pt-5 text-sm text-emerald-300">
 {links.map(([path,label])=><Link key={path} href={`${path}${league?`?league=${encodeURIComponent(league)}`:''}`}>{label}</Link>)}
 </nav>;
}
