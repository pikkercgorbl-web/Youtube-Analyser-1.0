"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  Bookmark,
  Flame,
  KeyRound,
  Layers,
  Menu,
  Radar,
  Search,
  Users,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";

import { SidebarNavGroup, SidebarNavItem } from "@/components/design-system/sidebar-nav";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

function isActivePath(pathname: string, href: string): boolean {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

const NAV_GROUPS = [
  {
    label: "Поиск и ключи",
    items: [
      { href: "/keyword-research", label: "Исследование ниш", icon: Search },
      { href: "/keywords", label: "Пул ключей", icon: Layers },
      { href: "/keyword-performance", label: "Производительность ключей", icon: BarChart3 },
    ],
  },
  {
    label: "Наблюдение",
    items: [
      { href: "/monitoring", label: "Мониторинг", icon: Radar },
      { href: "/operations", label: "Операции", icon: Activity },
    ],
  },
  {
    label: "Анализ",
    items: [
      { href: "/explosive-channels", label: "Взрывные каналы", icon: Flame },
      { href: "/mass-analysis", label: "Массовый анализ", icon: Users },
      { href: "/saved-keywords", label: "Сохранённые идеи", icon: Bookmark },
    ],
  },
] as const;

export function Sidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    if (!mobileOpen) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileOpen]);

  const closeMobile = () => setMobileOpen(false);

  const NavContent = () => (
    <>
      <div className="flex items-center gap-3 border-b border-border/60 px-5 py-6">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/20">
          <Zap className="h-5 w-5 text-primary" />
        </div>
        <div>
          <p className="text-sm font-semibold tracking-wide">NicheScope</p>
          <p className="text-xs text-muted-foreground">YouTube Analytics</p>
        </div>
      </div>

      <nav className="flex-1 px-3 py-2">
        <SidebarNavItem
          href="/"
          active={isActivePath(pathname, "/")}
          icon={KeyRound}
          label="Поиск видео"
          onNavigate={closeMobile}
        />
        {NAV_GROUPS.map((group) => (
          <SidebarNavGroup key={group.label} label={group.label}>
            {group.items.map(({ href, label, icon }) => (
              <SidebarNavItem
                key={href}
                href={href}
                active={isActivePath(pathname, href)}
                icon={icon}
                label={label}
                onNavigate={closeMobile}
              />
            ))}
          </SidebarNavGroup>
        ))}
      </nav>
    </>
  );

  return (
    <>
      <div className="sticky top-0 z-40 flex shrink-0 items-center justify-between border-b border-border/60 bg-background/95 px-3 py-3 backdrop-blur supports-[padding:max(0px)]:pt-[max(0.75rem,env(safe-area-inset-top))] lg:hidden">
        <div className="flex items-center gap-2">
          <Zap className="h-5 w-5 text-primary" />
          <span className="font-semibold">NicheScope</span>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-expanded={mobileOpen}
          aria-label={mobileOpen ? "Закрыть меню" : "Открыть меню"}
          onClick={() => setMobileOpen((value) => !value)}
        >
          {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </Button>
      </div>

      {mobileOpen ? (
        <div
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      ) : null}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-[min(280px,85vw)] shrink-0 flex-col border-r border-border/60 bg-card/95 backdrop-blur-xl transition-transform duration-200 ease-out lg:static lg:w-[250px] lg:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
      >
        <NavContent />
      </aside>
    </>
  );
}
