import "./styles.css";
import type { ReactNode } from "react";
import type { Viewport } from "next";
import { Suspense } from "react";
import { WorkspaceNav } from "@/components/WorkspaceNav";
// viewport-fit=cover makes env(safe-area-inset-bottom) real, so the bottom bar
// clears the iPhone home indicator instead of sitting under it.
export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover", themeColor: "#070d1a" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Suspense fallback={<div className="h-14 lg:hidden" aria-label="Loading navigation" />}><WorkspaceNav /></Suspense>
        <div id="workspace-content" className="pb-[calc(5rem+env(safe-area-inset-bottom))] lg:pb-12 lg:pl-60">{children}</div>
      </body>
    </html>
  );
}
