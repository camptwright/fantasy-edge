import {Suspense} from "react";
import {FantasyNav} from "@/components/FantasyNav";
export default function FantasyLayout({children}:{children:React.ReactNode}) {
 return <><Suspense fallback={<p className="p-5">Loading fantasy tools…</p>}><FantasyNav/></Suspense>{children}</>;
}
