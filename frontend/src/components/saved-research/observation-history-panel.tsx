"use client";

import { Button } from "@/components/ui/button";
import {
  formatMetricOrUnavailable,
  formatObservationWhen,
  formatVphValue,
} from "@/lib/saved-research-format";
import { DELAYED_OUTCOME_LABELS } from "@/lib/saved-research-labels";
import {
  familyHistoricalAnchorCounts,
  familyObservationPresenceLabel,
  familyObservationSourceLabel,
  isDailyIntelligenceAnchorPayload,
  observationSourceLabel,
  videoObservationAttentionLabel,
} from "@/lib/saved-research-format";
import { formatOptionalViews } from "@/lib/attention-format";
import type { SavedFamilyObservation, SavedVideoObservation } from "@/lib/saved-research-types";

type VideoProps = {
  kind: "video";
  items: SavedVideoObservation[];
  total: number;
  loading: boolean;
  onLoadMore?: () => void;
  hasMore: boolean;
};

type FamilyProps = {
  kind: "family";
  items: SavedFamilyObservation[];
  total: number;
  loading: boolean;
  onLoadMore?: () => void;
  hasMore: boolean;
};

export function ObservationHistoryPanel(props: VideoProps | FamilyProps) {
  const { items, total, loading, hasMore, onLoadMore } = props;

  let intro: string;
  if (total === 0) {
    intro = "Наблюдений пока нет.";
  } else if (total === 1) {
    intro = "Пока одна точка наблюдения.";
  } else {
    intro = `Точек наблюдения: ${total}.`;
  }

  const sectionTitle = props.kind === "family" ? "Наблюдения Attention" : "История наблюдений";
  const sectionLead =
    props.kind === "family"
      ? "Снимки темы из прогонов Attention Engine — отдельно от поиска новых видео по теме выше."
      : intro;

  return (
    <section className="rounded-xl border border-border p-4 space-y-3">
      <h2 className="font-semibold">{sectionTitle}</h2>
      <p className="text-sm text-muted-foreground">{props.kind === "family" ? sectionLead : intro}</p>
      {props.kind === "family" && total > 0 ? (
        <p className="text-sm text-muted-foreground">{intro}</p>
      ) : null}
      <ul className="space-y-3">
        {props.kind === "video"
          ? props.items.map((row) => (
              <li key={row.id} className="rounded-lg bg-muted/40 p-3 text-sm">
                <p className="font-medium">{formatObservationWhen(row.observed_at)}</p>
                {observationSourceLabel(row.payload) ? (
                  <p className="text-xs text-muted-foreground">
                    {observationSourceLabel(row.payload)}
                  </p>
                ) : null}
                <p>
                  Просмотры: {formatMetricOrUnavailable(formatOptionalViews(row.views))} · VPH:{" "}
                  {formatMetricOrUnavailable(formatVphValue(row.vph))}
                </p>
                <p className="text-muted-foreground">
                  {videoObservationAttentionLabel(row)} · Monitoring:{" "}
                  {row.monitoring_snapshot_available ? "снимок есть" : "снимок недоступен"}
                </p>
                {row.breakout_rank != null ? (
                  <p>Breakout #{row.breakout_rank}</p>
                ) : null}
                {row.delayed_outcome_state ? (
                  <p>
                    {DELAYED_OUTCOME_LABELS[row.delayed_outcome_state] ??
                      row.delayed_outcome_state}
                  </p>
                ) : null}
                {row.family_memberships.length > 0 ? (
                  <p>Темы: {row.family_memberships.map((f) => f.label).join(", ")}</p>
                ) : null}
              </li>
            ))
          : props.items.map((row) => {
              const anchor = isDailyIntelligenceAnchorPayload(row.payload);
              const anchorCounts = anchor ? familyHistoricalAnchorCounts(row.payload) : null;
              const videoCount =
                anchorCounts?.video_count ?? row.video_count;
              const channelCount =
                anchorCounts?.channel_count ?? row.channel_count;
              return (
              <li key={row.id} className="rounded-lg bg-muted/40 p-3 text-sm">
                <p className="font-medium">{formatObservationWhen(row.observed_at)}</p>
                {familyObservationSourceLabel(row.payload) ? (
                  <p className="text-xs text-muted-foreground">
                    {familyObservationSourceLabel(row.payload)}
                  </p>
                ) : null}
                {row.family_present || anchor ? (
                  <p>
                    {row.label ?? "—"} · видео{" "}
                    {formatMetricOrUnavailable(
                      videoCount != null ? String(videoCount) : null,
                    )}{" "}
                    · каналы{" "}
                    {formatMetricOrUnavailable(
                      channelCount != null ? String(channelCount) : null,
                    )}
                  </p>
                ) : (
                  <p className="text-muted-foreground">
                    {familyObservationPresenceLabel(row)}
                  </p>
                )}
              </li>
            );
            })}
      </ul>
      {hasMore ? (
        <Button type="button" variant="outline" size="sm" disabled={loading} onClick={onLoadMore}>
          {loading ? "Загрузка…" : "Показать ещё"}
        </Button>
      ) : null}
    </section>
  );
}
