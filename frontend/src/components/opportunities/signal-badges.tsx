"use client";

import { Badge } from "@/components/ui/badge";
import { humanReasonsForDisplay, winnerSignalFlags } from "@/lib/attention-format";
import { cn } from "@/lib/utils";

export function AttentionSignalBadges({
  reasonCodes,
  accelerationState,
  delayedOutcomeState,
  channelRelativeStatus,
  treatAsWinner,
  inWinnerSnapshot,
  className,
}: {
  reasonCodes?: string[];
  accelerationState?: string | null;
  delayedOutcomeState?: string | null;
  channelRelativeStatus?: string | null;
  treatAsWinner?: boolean;
  inWinnerSnapshot?: boolean;
  className?: string;
}) {
  const flags = winnerSignalFlags({
    reason_codes: reasonCodes,
    acceleration_state: accelerationState,
    delayed_outcome_state: delayedOutcomeState,
    channel_relative_signal: channelRelativeStatus ? { status: channelRelativeStatus } : null,
    in_winner_snapshot: inWinnerSnapshot,
  });
  const showWinner = treatAsWinner || flags.winner;
  const items: { key: string; label: string; className: string }[] = [];
  if (showWinner) {
    items.push({ key: "winner", label: "🔥 Winner", className: "border-amber-400/40 text-amber-200" });
  }
  if (flags.accelerating) {
    items.push({ key: "accel", label: "⚡ Ускоряется", className: "border-sky-400/40 text-sky-200" });
  }
  if (flags.confirmed72h) {
    items.push({ key: "72h", label: "✅ 72h подтверждено", className: "border-emerald-400/40 text-emerald-200" });
  }
  if (flags.smallChannel) {
    items.push({ key: "small", label: "🌱 Малый канал", className: "border-lime-400/35 text-lime-200" });
  }
  if (flags.strongerThanChannel) {
    items.push({
      key: "rel",
      label: "📈 Сильнее нормы канала",
      className: "border-violet-400/40 text-violet-200",
    });
  }
  if (items.length === 0) {
    return null;
  }
  return (
    <div className={cn("flex flex-wrap gap-1", className)} data-testid="signal-badges">
      {items.map((item) => (
        <Badge key={item.key} variant="outline" className={cn("font-normal", item.className)}>
          {item.label}
        </Badge>
      ))}
    </div>
  );
}

export function HumanReasonsList({ reasons }: { reasons: string[] }) {
  const items = humanReasonsForDisplay(reasons);
  if (items.length === 0) {
    return null;
  }
  return (
    <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground" data-testid="human-reasons">
      {items.map((reason) => (
        <li key={reason}>{reason}</li>
      ))}
    </ul>
  );
}
