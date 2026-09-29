"use client";

import { Badge } from "@/components/ui/badge";
import {
  checkpointStatusLabel,
  cycleStatusLabel,
  evidenceStatusLabel,
  lifecycleLabel,
  monitoringWorkerLabel,
  systemActivityLabel,
  type ActivityState,
  type CheckpointStatus,
  type CycleStatus,
  type EvidenceStatus,
  type LifecycleStatus,
  type MonitoringWorkerState,
} from "@/lib/design-system/labels";
import { cn } from "@/lib/utils";

type BadgeShellProps = {
  className?: string;
  title?: string;
  children: React.ReactNode;
};

function BadgeShell({ className, title, children }: BadgeShellProps) {
  return (
    <Badge variant="outline" className={cn("font-normal", className)} title={title}>
      {children}
    </Badge>
  );
}

export function SystemStatusBadge({
  state,
  title,
}: {
  state: ActivityState | MonitoringWorkerState | string;
  title?: string;
}) {
  const label =
    state === "running" || state === "stale" || state === "stopped" || state === "unknown"
      ? monitoringWorkerLabel(state)
      : systemActivityLabel(state);

  const tone = (() => {
    if (state === "active_recently" || state === "running") {
      return "border-status-ok/40 text-status-ok";
    }
    if (state === "stale_activity" || state === "stale") {
      return "border-status-warn/50 text-status-warn";
    }
    if (state === "error" || state === "stopped") {
      return "border-status-error/45 text-status-error";
    }
    return "border-border text-status-unknown";
  })();

  return <BadgeShell className={tone} title={title}>{label}</BadgeShell>;
}

export function LifecycleBadge({
  status,
  title,
  label,
}: {
  status: LifecycleStatus | null | undefined;
  title?: string;
  /** Override visible label (e.g. scheduling-focused pool copy). */
  label?: string;
}) {
  const normalized = (status ?? "").toLowerCase();
  const tone = (() => {
    switch (normalized) {
      case "probation":
        return "border-lifecycle-probation/50 text-lifecycle-probation bg-lifecycle-probation/10";
      case "active":
        return "border-lifecycle-active/45 text-lifecycle-active bg-lifecycle-active/10";
      case "weak":
        return "border-lifecycle-weak/50 text-lifecycle-weak bg-lifecycle-weak/10";
      case "archived":
        return "border-lifecycle-archived/40 text-lifecycle-archived bg-muted/30";
      default:
        return "border-border text-muted-foreground";
    }
  })();

  return (
    <BadgeShell className={cn("rounded-md", tone)} title={title}>
      {label ?? lifecycleLabel(status)}
    </BadgeShell>
  );
}

export function EvidenceBadge({
  status,
  title,
  label,
}: {
  status: EvidenceStatus | null | undefined;
  title?: string;
  /** Override visible label (e.g. keyword performance wording). */
  label?: string;
}) {
  const normalized = (status ?? "").toLowerCase();
  const tone = (() => {
    switch (normalized) {
      case "insufficient":
        return "border-evidence-insufficient/40 text-evidence-insufficient";
      case "early":
        return "border-evidence-early/50 text-evidence-early";
      case "established":
        return "border-evidence-established/45 text-evidence-established";
      default:
        return "border-border text-muted-foreground";
    }
  })();

  return (
    <BadgeShell className={tone} title={title}>
      {label ?? evidenceStatusLabel(status)}
    </BadgeShell>
  );
}

export function CheckpointBadge({
  status,
  title,
}: {
  status: CheckpointStatus | null | undefined;
  title?: string;
}) {
  const normalized = (status ?? "").toLowerCase();
  const tone = (() => {
    switch (normalized) {
      case "overdue":
        return "border-checkpoint-overdue/50 text-checkpoint-overdue";
      case "due":
        return "border-checkpoint-due/50 text-checkpoint-due";
      case "pending":
        return "border-checkpoint-pending/40 text-checkpoint-pending";
      case "active":
        return "border-checkpoint-done/40 text-checkpoint-done";
      case "stopped":
        return "border-border text-muted-foreground";
      default:
        return "border-border text-muted-foreground";
    }
  })();

  return (
    <BadgeShell className={tone} title={title}>
      {checkpointStatusLabel(status)}
    </BadgeShell>
  );
}

export type MonitoringVideoCheckpointInput = {
  monitoring_status: string;
  overdue_checkpoint_hours?: number[];
  due_checkpoint_hours?: number[];
};

/** For monitoring row: overdue beats due beats active. */
export function CheckpointBadgeFromVideo({ item }: { item: MonitoringVideoCheckpointInput }) {
  const overdue = item.overdue_checkpoint_hours ?? [];
  const due = item.due_checkpoint_hours ?? [];
  if (overdue.length > 0) {
    return <CheckpointBadge status="overdue" />;
  }
  if (due.length > 0) {
    return <CheckpointBadge status="due" />;
  }
  if (item.monitoring_status === "stopped") {
    return <CheckpointBadge status="stopped" />;
  }
  if (item.monitoring_status === "active") {
    return <CheckpointBadge status="active" />;
  }
  return <CheckpointBadge status={item.monitoring_status as CheckpointStatus} />;
}

export function CycleStatusBadge({
  status,
  showRawInTitle,
}: {
  status: CycleStatus | string;
  showRawInTitle?: boolean;
}) {
  const normalized = status.toLowerCase();
  const tone = (() => {
    if (normalized === "ok") {
      return "border-status-ok/40 text-status-ok font-mono text-xs";
    }
    if (normalized === "partial") {
      return "border-status-warn/50 text-status-warn font-mono text-xs";
    }
    if (normalized === "failed") {
      return "border-status-error/45 text-status-error font-mono text-xs";
    }
    return "border-border text-muted-foreground font-mono text-xs";
  })();

  return (
    <BadgeShell className={tone} title={showRawInTitle ? String(status) : undefined}>
      {cycleStatusLabel(status)}
    </BadgeShell>
  );
}

export function TierBadge({ tier }: { tier: string }) {
  const normalized = tier.toUpperCase();
  return (
    <Badge
      variant="outline"
      className={cn(
        "font-mono text-xs font-normal",
        normalized === "A" && "border-amber-500/40 text-amber-400/90",
        normalized === "B" && "border-sky-500/40 text-sky-400/90",
        normalized === "C" && "border-muted-foreground/35 text-muted-foreground",
      )}
    >
      Tier {normalized}
    </Badge>
  );
}

export function CapturePoolBadge({
  inActiveCapturePool,
  title,
}: {
  inActiveCapturePool: boolean;
  title?: string;
}) {
  if (inActiveCapturePool) {
    return (
      <Badge
        variant="outline"
        className="border-sky-500/35 font-normal text-sky-300/90"
        title={title}
      >
        В пуле наблюдения
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="border-border font-normal text-muted-foreground" title={title}>
      Вне пула наблюдения
    </Badge>
  );
}
