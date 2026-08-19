"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Today" },
  { href: "/team-odds", label: "Team odds" },
  { href: "/player-odds", label: "Player odds" },
  { href: "/games", label: "Games" },
  { href: "/favorites", label: "Favorites" },
  { href: "/parlays", label: "Parlay builder" },
  { href: "/model-lab", label: "Model lab" },
  { href: "/paper-tracker", label: "Paper tracker" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="border-b border-border bg-surface/95" aria-label="Sports workspace">
      <div className="mx-auto flex max-w-7xl items-center gap-5 px-4 py-3 lg:px-6">
        <Link href="/" className="mr-2 flex min-w-fit items-center gap-2" aria-label="Sports home">
          <span className="h-2.5 w-2.5 rounded-full bg-accent shadow-[0_0_16px_rgba(99,196,154,0.65)]" />
          <span className="font-semibold tracking-tight text-gray-100">Sports</span>
        </Link>
        <div className="hidden items-center gap-0.5 overflow-x-auto md:flex">
          {LINKS.map((link, index) => {
            const active = link.href === "/" ? pathname === "/" : pathname?.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`rounded-md px-2.5 py-1.5 text-sm transition-colors ${
                active
                  ? "bg-accent/10 text-accent"
                  : "text-gray-400 hover:bg-white/5 hover:text-gray-200"
              }`}
            >
              {link.label}
            </Link>
          );
          })}
        </div>
        <div className="ml-auto hidden items-center gap-2 text-xs text-gray-500 lg:flex">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          Shared workspace
        </div>
      </div>
      <div className="flex gap-1 overflow-x-auto px-4 pb-2 md:hidden" aria-label="Mobile navigation">
        {LINKS.slice(0, 5).map((link) => {
          const active = link.href === "/" ? pathname === "/" : pathname?.startsWith(link.href);
          return <Link key={link.href} href={link.href} className={`min-h-11 whitespace-nowrap rounded-md px-3 py-2 text-sm ${active ? "bg-accent/10 text-accent" : "text-gray-400"}`}>{link.label}</Link>;
        })}
      </div>
    </nav>
  );
}
