import "./styles.css";
import type { ReactNode } from "react";
import { Suspense } from "react";
import { Nav } from "@/components/Nav";
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Suspense fallback={<div className="h-16" aria-label="Loading navigation" />}><Nav /></Suspense>
        {children}
      </body>
    </html>
  );
}
