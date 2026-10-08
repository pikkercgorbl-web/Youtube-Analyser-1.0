"use client";

import Link from "next/link";

import { usePathname } from "next/navigation";

import {
  Activity,
  BarChart3,
  Bookmark,
  Flame,
  Layers,
  Menu,
  Radar,
  Search,
  Users,
  X,
  Zap,
} from "lucide-react";

import { useEffect, useState } from "react";

import {
  SidebarNavGroup,
  SidebarNavItem,
} from "@/components/design-system/sidebar-nav";

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
    label: "Разведка",
    items: [
      { href: "/opportunities", label: "Возможности", icon: Flame },
      { href: "/saved-topics", label: "Сохранённые темы", icon: Bookmark },
      { href: "/validation", label: "Результаты решений", icon: BarChart3 },
    ],
  },
  {
    label: "Поиск",
    items: [
      { href: "/", label: "Ручной поиск", icon: Search },
      { href: "/mass-analysis", label: "Анализ конкурентов", icon: Users },
      { href: "/keywords", label: "Поисковые запросы", icon: Layers },
      {
        href: "/keyword-performance",
        label: "Отдача запросов",
        icon: BarChart3,
      },
    ],
  },
  {
    label: "Сбор данных",
    items: [
      { href: "/monitoring", label: "Наблюдение за видео", icon: Radar },
      { href: "/operations", label: "Состояние системы", icon: Activity },
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

  useEffect(() => {
    if (!mobileOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [mobileOpen]);
  const closeMobile = () => setMobileOpen(false);

  const NavContent = () => (
    <>
      <div className="flex items-center gap-3 border-b border-border/60 px-5 py-6">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/20">
          <Zap className="h-5 w-5 text-primary" />
        </div>

        <div>
          <p className="text-xl font-semibold tracking-tight">NicheScope</p>

          <p className="text-xs text-muted-foreground">Разведка YouTube</p>
        </div>
      </div>

      <nav
        aria-label="Основная навигация"
        className="flex-1 overflow-y-auto px-3 py-2"
      >
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
          {mobileOpen ? (
            <X className="h-5 w-5" />
          ) : (
            <Menu className="h-5 w-5" />
          )}
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
          "fixed inset-y-0 left-0 z-40 flex w-[min(280px,85vw)] shrink-0 flex-col border-r border-border/60 bg-card/95 backdrop-blur-xl transition-transform duration-200 ease-out lg:sticky lg:top-0 lg:h-screen lg:w-[250px] lg:translate-x-0",

          mobileOpen
            ? "translate-x-0 visible"
            : "-translate-x-full invisible lg:visible lg:translate-x-0",
        )}
      >
        <button
          type="button"
          onClick={closeMobile}
          aria-label="Закрыть навигацию"
          className="absolute right-3 top-3 rounded-lg p-2 lg:hidden"
        >
          <X className="h-4 w-4" />
        </button>
        <NavContent />
      </aside>
    </>
  );
}
