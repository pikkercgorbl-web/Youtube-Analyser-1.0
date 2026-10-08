"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import {
  Disclosure,
  ErrorState,
  LoadingState,
  PageHeader,
  PageShell,
  SectionPanel,
} from "@/components/design-system";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  addSavedTopicFeedback,
  archiveSavedTopic,
  getSavedTopic,
  getSavedTopicTimeline,
  patchSavedTopic,
  restoreSavedTopic,
} from "@/lib/api";
import { canonicalYoutubeUrl, familyDetailHref } from "@/lib/attention-format";
import {
  EVENT_TYPE_LABELS,
  FAMILY_ABSENCE_MESSAGE,
  FINDING_RATING_LABELS,
  OWN_TEST_OUTCOME_LABELS,
  SAVED_TOPIC_STATUS_LABELS,
} from "@/lib/saved-topics";
import type {
  FindingRating,
  OwnTestOutcome,
  SavedTopicDetail,
  SavedTopicStatus,
  SavedTopicTimelineItem,
} from "@/lib/saved-topics-types";
import { cn } from "@/lib/utils";

const STATUSES: SavedTopicStatus[] = [
  "WATCHING",
  "WANT_TO_TEST",
  "TESTING",
  "DROPPED",
];
const FINDING_RATINGS: FindingRating[] = ["USEFUL", "NOT_USEFUL", "UNCLEAR"];
const TEST_OUTCOMES: OwnTestOutcome[] = [
  "UNKNOWN",
  "BETTER",
  "AS_EXPECTED",
  "WORSE",
];

function formatTimelineItem(item: SavedTopicTimelineItem): string {
  if (item.kind === "observation") {
    return formatCounts(item.payload);
  }
  const type = item.event_type ?? "event";
  const label = EVENT_TYPE_LABELS[type] ?? type;
  if (type === "status_changed" && item.payload) {
    const prev = item.payload.previous_status;
    const next = item.payload.new_status;
    return `${label}: ${String(prev)} → ${String(next)}`;
  }
  if (type === "feedback_added" && item.payload) {
    const rating = item.payload.finding_rating;
    return `${label}: ${FINDING_RATING_LABELS[String(rating)] ?? String(rating)}`;
  }
  return label;
}

function snapshotFamily(
  snapshot: Record<string, unknown>,
): Record<string, unknown> {
  const family = snapshot.family;
  return family && typeof family === "object"
    ? (family as Record<string, unknown>)
    : {};
}

function videoLinks(
  snapshot: Record<string, unknown>,
): { video_id: string; title?: string; youtube_url?: string }[] {
  const evidence = snapshot.breakout_video_evidence;
  if (!Array.isArray(evidence)) return [];
  return evidence
    .filter(
      (row): row is Record<string, unknown> =>
        typeof row === "object" && row !== null && "video_id" in row,
    )
    .map((row) => ({
      video_id: String(row.video_id),
      title: row.title ? String(row.title) : undefined,
      youtube_url: row.youtube_url
        ? String(row.youtube_url)
        : canonicalYoutubeUrl(String(row.video_id)),
    }));
}

function formatCounts(payload: Record<string, unknown> | undefined): string {
  if (!payload) return "—";
  const counts = payload.counts;
  if (!counts || typeof counts !== "object") {
    if (payload.present_in_snapshot === false) {
      return String(payload.absence_message ?? FAMILY_ABSENCE_MESSAGE);
    }
    return "—";
  }
  const c = counts as Record<string, number>;
  return [
    `видео ${c.video_count ?? "?"}`,
    `каналы ${c.channel_count ?? "?"}`,
    `ключи ${c.keyword_count ?? "?"}`,
    `допущено к анализу ${c.breakout_eligible_count ?? "?"}`,
  ].join(" · ");
}

export function SavedTopicDetailView({ topicId }: { topicId: number }) {
  const [detail, setDetail] = useState<SavedTopicDetail | null>(null);
  const [timeline, setTimeline] = useState<SavedTopicTimelineItem[]>([]);
  const [state, setState] = useState<"loading" | "error" | "ready">("loading");
  const [message, setMessage] = useState("");
  const [notes, setNotes] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [status, setStatus] = useState<SavedTopicStatus>("WATCHING");
  const [saving, setSaving] = useState(false);
  const [findingRating, setFindingRating] = useState<FindingRating>("UNCLEAR");
  const [feedbackComment, setFeedbackComment] = useState("");
  const [testUrl, setTestUrl] = useState("");
  const [testPublished, setTestPublished] = useState("");
  const [testOutcome, setTestOutcome] = useState<OwnTestOutcome>("UNKNOWN");
  const [metricViews, setMetricViews] = useState("");
  const [metricVph, setMetricVph] = useState("");
  const [metricMeasuredAt, setMetricMeasuredAt] = useState("");
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setState("loading");
    try {
      const [topic, tl] = await Promise.all([
        getSavedTopic(topicId),
        getSavedTopicTimeline(topicId, { limit: 50, offset: 0 }),
      ]);
      setDetail(topic);
      setTimeline(tl.items);
      setNotes(topic.notes);
      setTagsText(topic.tags.join(", "));
      setStatus(topic.status);
      setState("ready");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Тема не найдена");
      setState("error");
    }
  }, [topicId]);

  useEffect(() => {
    void load();
  }, [load]);

  const frozenFamily = useMemo(
    () => (detail ? snapshotFamily(detail.frozen_snapshot) : {}),
    [detail],
  );

  const livePayload = detail?.live_observation?.payload;

  const onSaveMeta = async () => {
    setSaving(true);
    try {
      const tags = tagsText
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean);
      const updated = await patchSavedTopic(topicId, { notes, tags, status });
      setDetail(updated);
      const tl = await getSavedTopicTimeline(topicId, { limit: 50, offset: 0 });
      setTimeline(tl.items);
    } finally {
      setSaving(false);
    }
  };

  const onArchive = async () => {
    const updated = await archiveSavedTopic(topicId);
    setDetail(updated);
  };

  const onRestore = async () => {
    const updated = await restoreSavedTopic(topicId);
    setDetail(updated);
    const tl = await getSavedTopicTimeline(topicId, { limit: 50, offset: 0 });
    setTimeline(tl.items);
  };

  const onSubmitFeedback = async () => {
    setFeedbackSaving(true);
    setFeedbackError(null);
    try {
      const manual =
        metricViews || metricVph || metricMeasuredAt
          ? {
              views: metricViews ? Number.parseInt(metricViews, 10) : null,
              vph: metricVph ? Number.parseFloat(metricVph) : null,
              measured_at: metricMeasuredAt
                ? new Date(metricMeasuredAt).toISOString()
                : null,
            }
          : null;
      await addSavedTopicFeedback(topicId, {
        finding_rating: findingRating,
        reason_comment: feedbackComment,
        own_test_video_url: testUrl.trim() || null,
        own_test_video_published_at: testPublished
          ? new Date(testPublished).toISOString()
          : null,
        own_test_outcome: testOutcome,
        manual_metrics: manual,
      });
      const [topic, tl] = await Promise.all([
        getSavedTopic(topicId),
        getSavedTopicTimeline(topicId, { limit: 50, offset: 0 }),
      ]);
      setDetail(topic);
      setTimeline(tl.items);
    } catch (error) {
      setFeedbackError(
        error instanceof Error ? error.message : "Не удалось сохранить оценку",
      );
    } finally {
      setFeedbackSaving(false);
    }
  };

  if (state === "loading") return <LoadingState title="Загрузка темы…" />;
  if (state === "error")
    return <ErrorState title={message} onRetry={() => void load()} />;
  if (!detail) return null;

  const label = String(frozenFamily.label ?? detail.family_key);
  const examples = videoLinks(detail.frozen_snapshot);

  return (
    <PageShell>
      <Link
        href="/saved-topics"
        className={cn(
          buttonVariants({ variant: "ghost", size: "sm" }),
          "w-fit",
        )}
      >
        <ArrowLeft className="mr-1 h-4 w-4" />
        Сохранённые темы
      </Link>
      <PageHeader
        title={label}
        lead="Сравните исходную находку с последними наблюдениями и запишите своё решение."
      />
      {detail.archived_at ? (
        <p className="text-sm text-amber-200">
          В архиве с {new Date(detail.archived_at).toLocaleString()}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionPanel title="При сохранении">
          <p className="text-lg font-medium">
            {String(frozenFamily.video_count ?? "—")} видео ·{" "}
            {String(frozenFamily.channel_count ?? "—")} каналов
          </p>
          <Disclosure summary="Исходные данные сохранения">
            <pre className="max-h-64 overflow-auto text-xs">
              {JSON.stringify(frozenFamily, null, 2)}
            </pre>
          </Disclosure>
          {examples.length ? (
            <ul className="mt-3 space-y-1 text-sm">
              {examples.slice(0, 8).map((video) => (
                <li key={video.video_id}>
                  <a
                    href={video.youtube_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary hover:underline"
                  >
                    {video.title ?? video.video_id}
                  </a>
                </li>
              ))}
            </ul>
          ) : null}
        </SectionPanel>

        <SectionPanel title="Последнее наблюдение">
          {detail.live_observation ? (
            <>
              <p className="text-xs text-muted-foreground">
                {new Date(detail.live_observation.captured_at).toLocaleString()}{" "}
                · run {detail.live_observation.attention_run_id}
              </p>
              <p className="mt-2 text-sm">{formatCounts(livePayload)}</p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              Новых наблюдений пока нет.
            </p>
          )}
          {detail.count_deltas ? (
            <Disclosure summary="Изменения показателей">
              <ul className="text-xs">
                {Object.entries(detail.count_deltas).map(([key, delta]) => (
                  <li key={key}>
                    {key}: {delta > 0 ? "+" : ""}
                    {delta}
                  </li>
                ))}
              </ul>
            </Disclosure>
          ) : null}
        </SectionPanel>
      </div>

      <SectionPanel title="Оценка находки и собственный тест">
        <p className="text-xs text-muted-foreground">
          Новая запись сохраняет предыдущие оценки. Метрики своего видео — ваши
          ручные данные, отдельно от измерений Radar.
        </p>
        {detail.latest_feedback ? (
          <p className="mt-2 text-sm">
            Последняя оценка:{" "}
            {FINDING_RATING_LABELS[detail.latest_feedback.finding_rating]} (
            {new Date(detail.latest_feedback.recorded_at).toLocaleString()})
          </p>
        ) : null}
        <div className="mt-3 flex max-w-lg flex-col gap-3">
          <label className="text-sm">
            Оценка находки
            <select
              className="mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={findingRating}
              onChange={(event) =>
                setFindingRating(event.target.value as FindingRating)
              }
            >
              {FINDING_RATINGS.map((value) => (
                <option key={value} value={value}>
                  {FINDING_RATING_LABELS[value]}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Причина / комментарий
            <Textarea
              className="mt-1"
              value={feedbackComment}
              onChange={(event) => setFeedbackComment(event.target.value)}
              rows={3}
            />
          </label>
          <label className="text-sm">
            Ссылка на тестовое видео (необязательно)
            <Input
              className="mt-1"
              value={testUrl}
              onChange={(event) => setTestUrl(event.target.value)}
            />
          </label>
          <label className="text-sm">
            Дата публикации тестового видео
            <Input
              className="mt-1"
              type="datetime-local"
              value={testPublished}
              onChange={(event) => setTestPublished(event.target.value)}
            />
          </label>
          <label className="text-sm">
            Результат собственного теста
            <select
              className="mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={testOutcome}
              onChange={(event) =>
                setTestOutcome(event.target.value as OwnTestOutcome)
              }
            >
              {TEST_OUTCOMES.map((value) => (
                <option key={value} value={value}>
                  {OWN_TEST_OUTCOME_LABELS[value]}
                </option>
              ))}
            </select>
          </label>
          <Disclosure summary="Ручные показатели своего видео">
            <div className="flex flex-col gap-2 pt-2">
              <Input
                placeholder="Просмотры"
                value={metricViews}
                onChange={(event) => setMetricViews(event.target.value)}
              />
              <Input
                placeholder="VPH"
                value={metricVph}
                onChange={(event) => setMetricVph(event.target.value)}
              />
              <Input
                type="datetime-local"
                value={metricMeasuredAt}
                onChange={(event) => setMetricMeasuredAt(event.target.value)}
              />
            </div>
          </Disclosure>
          {feedbackError ? (
            <p className="text-xs text-destructive">{feedbackError}</p>
          ) : null}
          <Button
            type="button"
            disabled={feedbackSaving}
            onClick={() => void onSubmitFeedback()}
          >
            Добавить оценку
          </Button>
        </div>
      </SectionPanel>

      <SectionPanel title="Статус, заметки, теги">
        <div className="flex max-w-lg flex-col gap-3">
          <label className="text-sm">
            Статус
            <select
              className="mt-1 flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={status}
              onChange={(event) =>
                setStatus(event.target.value as SavedTopicStatus)
              }
            >
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {SAVED_TOPIC_STATUS_LABELS[value]}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Заметки
            <Textarea
              className="mt-1"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              rows={4}
            />
          </label>
          <label className="text-sm">
            Теги (через запятую)
            <Input
              className="mt-1"
              value={tagsText}
              onChange={(event) => setTagsText(event.target.value)}
            />
          </label>
          <Button
            type="button"
            disabled={saving}
            onClick={() => void onSaveMeta()}
          >
            Сохранить изменения
          </Button>
        </div>
      </SectionPanel>

      <SectionPanel title="История наблюдений и решений">
        {timeline.length === 0 ? (
          <p className="text-sm text-muted-foreground">Пусто</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {timeline.map((row) => (
              <li
                key={`${row.kind}-${row.observation_id ?? row.id ?? row.occurred_at}`}
                className="rounded-md border border-border/60 p-3"
              >
                <p className="text-xs text-muted-foreground">
                  {new Date(row.occurred_at).toLocaleString()}
                  {row.kind === "observation" && row.attention_run_id
                    ? ` · ${row.attention_run_id}`
                    : ""}
                  {row.kind === "event" ? ` · ${row.kind}` : ""}
                </p>
                <p>{formatTimelineItem(row)}</p>
              </li>
            ))}
          </ul>
        )}
      </SectionPanel>

      <div className="flex flex-wrap gap-2">
        <Link
          href={familyDetailHref(detail.family_key)}
          className={buttonVariants({ variant: "outline", size: "sm" })}
        >
          Открыть семейство (live Attention UI)
        </Link>
        {detail.archived_at ? (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => void onRestore()}
          >
            Восстановить
          </Button>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void onArchive()}
          >
            В архив
          </Button>
        )}
      </div>
    </PageShell>
  );
}
