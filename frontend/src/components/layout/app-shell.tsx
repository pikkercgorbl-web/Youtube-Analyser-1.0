"use client";

import { Sidebar } from "@/components/layout/sidebar";

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-background">
      <div className="flex min-h-screen">
        <Sidebar />
        <main className="flex min-h-screen flex-1 flex-col overflow-x-hidden">{children}</main>
      </div>
    </div>
  );
}
