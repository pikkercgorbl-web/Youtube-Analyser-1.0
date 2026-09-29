"use client";

import { pageLayout } from "@/lib/design-system/layout";
import { textRoles } from "@/lib/design-system/typography";
import { cn } from "@/lib/utils";

export function PageShell({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn(pageLayout.padding, pageLayout.sectionGap, className)}>{children}</div>;
}

export function PageHeader({
  icon,
  title,
  lead,
  actions,
}: {
  icon?: React.ReactNode;
  title: string;
  lead?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h1 className={cn(textRoles.pageTitle, "flex items-center gap-2")}>
          {icon}
          {title}
        </h1>
        {lead ? <p className={textRoles.pageLead}>{lead}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function SectionPanel({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn(pageLayout.blockGap, className)}>
      <div>
        <h2 className={textRoles.sectionTitle}>{title}</h2>
        {description ? <p className={cn(textRoles.sectionDescription, "mt-1")}>{description}</p> : null}
      </div>
      {children}
    </section>
  );
}
