"use client";

import { Sidebar } from "@/components/layout/sidebar";

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="radar-workspace min-h-screen">
      <div className="flex min-h-screen flex-col lg:flex-row">
        <Sidebar />
        <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-x-hidden">{children}</main>
      </div>
    </div>
  );
}
