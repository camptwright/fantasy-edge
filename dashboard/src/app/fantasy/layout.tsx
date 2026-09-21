import Link from "next/link";
export default function FantasyLayout({children}:{children:React.ReactNode}) {
 return <><nav aria-label="Fantasy tools" className="mx-auto flex max-w-6xl flex-wrap gap-4 px-5 pt-5 text-sm text-emerald-300"><Link href="/fantasy">Roster & waivers</Link><Link href="/fantasy/matchup">Matchup</Link><Link href="/fantasy/trade">Trade desk</Link><Link href="/fantasy/values">Player values & trade impact</Link><Link href="/fantasy/models">Matchup / waiver / ROS candidates</Link></nav>{children}</>;
}
