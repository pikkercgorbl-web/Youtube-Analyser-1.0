"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";

import { CheckpointBadge, CycleStatusBadge, MonitoringStatusBadge, TierBadge } from "@/components/monitoring/monitoring-badges";
import { InfoTooltip } from "@/components/design-system";
import { CHECKPOINT_HELP, TIER_OPERATIONAL_HELP } from "@/lib/monitoring-summaries";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StateMessage } from "@/components/ui/state-message";
import { getMonitoringSnapshots, getMonitoringVideo } from "@/lib/api";
import {
  formatAgeHours,
  formatDateTimeLocal,
  formatMonitoringViews,
  formatMonitoringVph,
} from "@/lib/monitoring-format";
import type { MonitoringSnapshot, MonitoringVideoDetail } from "@/lib/monitoring-types";
import { formatNumber } from "@/lib/utils";

export function MonitoringVideoDetailView({ videoId }: { videoId: string }) {
  const [detail, setDetail] = useState<MonitoringVideoDetail | null>(null);
  const [snapshots, setSnapshots] = useState<MonitoringSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [snapshotsLoading, setSnapshotsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getMonitoringVideo(videoId);
      setDetail(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Видео не найдено");
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, [videoId]);

  const loadSnapshots = useCallback(async () => {
    setSnapshotsLoading(true);
    try {
      const rows = await getMonitoringSnapshots(videoId, { limit: 100 });
      setSnapshots(rows);
    } catch {
      setSnapshots([]);
    } finally {
      setSnapshotsLoading(false);
    }
  }, [videoId]);

  useEffect(() => {
    void load();
    void loadSnapshots();
  }, [load, loadSnapshots]);

  if (loading) {
    return <StateMessage variant="loading" title="Загрузка видео…" />;
  }

  if (error || !detail) {
    return (
      <div className="space-y-4">
        <Link href="/monitoring" className="inline-flex items-center text-sm text-primary hover:underline">
          <ArrowLeft className="mr-1 h-4 w-4" /> К мониторингу
        </Link>
        <StateMessage variant="error" title="Не удалось загрузить видео" description={error ?? undefined} />
      </div>
    );
  }

  const baseline = detail.channel_baseline;

  return (
    <div className="space-y-8 pb-10">
      <div className="flex flex-col gap-2">
        <Link href="/monitoring" className="inline-flex items-center text-sm text-primary hover:underline">
          <ArrowLeft className="mr-1 h-4 w-4" /> К мониторингу
        </Link>
        <h1 className="text-2xl font-semibold">{detail.title ?? detail.video_id}</h1>
        <p className="text-sm text-muted-foreground">{detail.channel_title ?? detail.channel_id}</p>
        <div className="flex flex-wrap items-center gap-2">
          <TierBadge tier={detail.tier} />
          <InfoTooltip content={TIER_OPERATIONAL_HELP} />
          <MonitoringStatusBadge
            item={{
              monitoring_status: detail.monitoring_status,
              due_checkpoint_hours: detail.checkpoints.filter((c) => c.status === "due").map((c) => c.target_age_hours),
              overdue_checkpoint_hours: detail.checkpoints
                .filter((c) => c.status === "overdue")
                .map((c) => c.target_age_hours),
            }}
          />
        </div>
      </div>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-border/70 p-4">
          <p className="text-xs text-muted-foreground">Просмотры</p>
          <p className="text-xl font-semibold tabular-nums">{formatMonitoringViews(detail.views)}</p>
        </div>
        <div className="rounded-xl border border-border/70 p-4">
          <p className="text-xs text-muted-foreground">VPH</p>
          <p className="text-xl font-semibold tabular-nums">{formatMonitoringVph(detail.vph)}</p>
        </div>
        <div className="rounded-xl border border-border/70 p-4">
          <p className="text-xs text-muted-foreground">Возраст</p>
          <p className="text-xl font-semibold tabular-nums">{formatAgeHours(detail.age_hours)}</p>
        </div>
        <div className="rounded-xl border border-border/70 p-4">
          <p className="text-xs text-muted-foreground">Subscribers (snapshot)</p>
          <p className="text-xl font-semibold tabular-nums">
            {detail.subscribers != null ? formatNumber(detail.subscribers) : "—"}
          </p>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium flex items-center gap-2">
          Контрольные точки
          <InfoTooltip content={CHECKPOINT_HELP} />
        </h2>
        <div className="overflow-x-auto rounded-xl border border-border/70">
          <table className="min-w-full text-sm">
            <thead className="border-b border-border/60 bg-muted/30 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Горизонт (ч)</th>
                <th className="px-3 py-2">Состояние</th>
                <th className="px-3 py-2">Снимок (ч)</th>
                <th className="px-3 py-2">Due с (ч)</th>
                <th className="px-3 py-2">Истекает (ч)</th>
                <th className="px-3 py-2">Действие</th>
              </tr>
            </thead>
            <tbody>
              {detail.checkpoints.map((cp) => (
                <tr key={cp.target_age_hours} className="border-b border-border/40">
                  <td className="px-3 py-2 font-mono">{cp.target_age_hours}</td>
                  <td className="px-3 py-2">
                    <CheckpointBadge status={cp.status} />
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {cp.matched_snapshot_age_hours != null ? `${cp.matched_snapshot_age_hours}h` : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {cp.due_since_hours != null ? `${cp.due_since_hours}h` : "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums">{cp.expires_at_age_hours}h</td>
                  <td className="px-3 py-2 text-muted-foreground">{cp.recommended_action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {detail.stop_reason ? (
          <p className="text-sm text-muted-foreground">Причина остановки: {detail.stop_reason}</p>
        ) : null}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Базовая линия канала</h2>
        {baseline ? (
          <div className="grid gap-2 rounded-xl border border-border/70 p-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
            <div>
              Status: <CycleStatusBadge status={baseline.baseline_status} />
            </div>
            <div>Comparable videos: {baseline.comparable_video_count ?? "—"}</div>
            <div>Median VPH: {formatMonitoringVph(baseline.median_vph)}</div>
            <div>P75 VPH: {formatMonitoringVph(baseline.p75_vph)}</div>
            <div>vs median: {baseline.vph_vs_channel_median?.toFixed(2) ?? "—"}×</div>
            <div>vs P75: {baseline.vph_vs_channel_p75?.toFixed(2) ?? "—"}×</div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Baseline недоступен для этого видео.</p>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">История снимков</h2>
        {snapshotsLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Загрузка…
          </div>
        ) : snapshots.length === 0 ? (
          <p className="text-sm text-muted-foreground">Снимков пока нет.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-border/70">
            <table className="min-w-full text-sm">
              <thead className="border-b border-border/60 bg-muted/30 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">Captured</th>
                  <th className="px-3 py-2">Age</th>
                  <th className="px-3 py-2">Views</th>
                  <th className="px-3 py-2">VPH</th>
                  <th className="px-3 py-2">Subs</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.map((snap) => (
                  <tr key={`${snap.captured_at}-${snap.run_id}`} className="border-b border-border/40">
                    <td className="px-3 py-2">{formatDateTimeLocal(snap.captured_at)}</td>
                    <td className="px-3 py-2">{formatAgeHours(snap.age_hours)}</td>
                    <td className="px-3 py-2">{formatMonitoringViews(snap.views)}</td>
                    <td className="px-3 py-2">{formatMonitoringVph(snap.vph)}</td>
                    <td className="px-3 py-2">
                      {snap.subscribers != null ? formatNumber(snap.subscribers) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
