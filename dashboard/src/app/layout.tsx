import "./styles.css";
import type { ReactNode } from "react";
import { Suspense } from "react";
import { WorkspaceNav } from "@/components/WorkspaceNav";
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Suspense fallback={<div className="h-14 lg:hidden" aria-label="Loading navigation" />}><WorkspaceNav /></Suspense>
        <div id="workspace-content" className="pb-24 lg:pb-12 lg:pl-60">{children}</div>
      </body>
    </html>
  );
}
