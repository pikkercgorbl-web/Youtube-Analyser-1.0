"use client";

import Link from "next/link";

import { cn } from "@/lib/utils";

/** Visual foundation for 1.21F — group headings in sidebar. */
export function SidebarNavGroup({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1", className)} data-testid="sidebar-nav-group">
      <p className="px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
        {label}
      </p>
      {children}
    </div>
  );
}

export function SidebarNavItem({
  href,
  active,
  icon: Icon,
  label,
  onNavigate,
}: {
  href: string;
  active: boolean;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
        active
          ? "bg-primary/10 text-primary ring-1 ring-primary/20"
          : "text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {label}
    </Link>
  );
}
