import {
  formatOptionalAge,
  formatOptionalViews,
  formatOptionalVph,
} from "@/lib/attention-format";
import type { AttentionPatternMemberVideo } from "@/lib/attention-types";
import {
  formatViewsWithMeasurementStatus,
  viewsMeasurementLabel,
  type ViewsMeasurementStatus,
} from "@/lib/views-measurement-status";

export function memberMetricOrMissing(
  formatted: string | null,
  status: ViewsMeasurementStatus | string,
  kind: "views" | "vph" | "age",
): string {
  if (formatted) {
    return formatted;
  }
  if (
    kind === "views" &&
    (status === "zero_in_snapshot" || status === "zero_in_winner_snapshot")
  ) {
    return "0";
  }
  return "Нет измерения";
}

export function memberMetricCaption(
  video: AttentionPatternMemberVideo,
  snapshotComputedAt: string | null,
): string {
  const status = video.views_measurement_status ?? "missing_snapshot";
  const base = viewsMeasurementLabel(status);
  if (snapshotComputedAt && video.in_winner_snapshot) {
    return `${base} · run Attention ${formatSnapshotUtcDay(snapshotComputedAt)}`;
  }
  if (snapshotComputedAt) {
    return `${base} · на момент снимка ${formatSnapshotUtcDay(snapshotComputedAt)}`;
  }
  return base;
}

export function formatSnapshotUtcDay(iso: string | null): string {
  if (!iso) {
    return "—";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  return date.toISOString().slice(0, 10);
}

export function memberDisplayMetrics(video: AttentionPatternMemberVideo) {
  const status = video.views_measurement_status ?? "missing_snapshot";
  const views = memberMetricOrMissing(
    formatViewsWithMeasurementStatus(formatOptionalViews(video.views), status),
    status,
    "views",
  );
  const vph = memberMetricOrMissing(formatOptionalVph(video.vph), status, "vph");
  const age = memberMetricOrMissing(formatOptionalAge(video.age_hours), status, "age");
  return { views, vph, age, status };
}
