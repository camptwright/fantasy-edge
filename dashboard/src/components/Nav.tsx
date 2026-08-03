"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/signals", label: "Signals" },
  { href: "/games", label: "Games" },
  { href: "/props", label: "Props" },
  { href: "/parlays", label: "Parlays" },
  { href: "/fantasy", label: "Fantasy" },
  { href: "/rankings", label: "Rankings" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="border-b border-border bg-surface">
      <div className="mx-auto flex max-w-6xl items-center gap-1 px-4 py-3">
        <span className="mr-4 font-semibold text-accent">Fantasy Edge</span>
        {LINKS.map((link) => {
          const active = pathname?.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
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
    </nav>
  );
}
