"use client";

import { InfoTooltip } from "@/components/design-system/info-tooltip";
import { textRoles } from "@/lib/design-system/typography";
import { cn } from "@/lib/utils";

export function Metric({
  label,
  value,
  helper,
  tooltip,
  testId,
  valueClassName,
}: {
  label: string;
  value: React.ReactNode;
  helper?: string;
  tooltip?: string;
  testId?: string;
  valueClassName?: string;
}) {
  return (
    <div data-testid={testId}>
      <div className="flex items-center gap-1">
        <p className={textRoles.metricLabel}>{label}</p>
        {tooltip ? <InfoTooltip content={tooltip} /> : null}
      </div>
      <p className={cn(textRoles.metricValue, valueClassName)}>{value}</p>
      {helper ? <p className={cn(textRoles.helper, "mt-0.5")}>{helper}</p> : null}
    </div>
  );
}

export function MetricGroup({
  title,
  description,
  children,
  className,
}: {
  title?: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-3", className)} data-testid="metric-group">
      {title ? <h3 className={textRoles.sectionTitle}>{title}</h3> : null}
      {description ? <p className={textRoles.sectionDescription}>{description}</p> : null}
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">{children}</div>
    </section>
  );
}
