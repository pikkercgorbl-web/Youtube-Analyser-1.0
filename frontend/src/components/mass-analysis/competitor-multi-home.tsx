"use client";

import Image from "next/image";
import { useCallback, useMemo, useRef, useState } from "react";
import { Play, RefreshCw, Users } from "lucide-react";

import { CompetitorPublicationCard } from "@/components/mass-analysis/competitor-publication-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { StateMessage } from "@/components/ui/state-message";
import { Textarea } from "@/components/ui/textarea";
import { fetchCompetitorChannelPreview } from "@/lib/api";
import { samplePeriodLabel } from "@/lib/channel-single-analysis-overview";
import { sortRegularPublicationsUnknownLast } from "@/lib/competitor-multi-feed";
import type { RegularSortMode } from "@/lib/channel-single-analysis-overview";
import {
  applyChannelPreviewError,
  applyChannelPreviewSuccess,
  buildUniqueChannelViews,
  COMPETITOR_MAX_CHANNELS,
  COMPETITOR_MIN_CHANNELS,
  createInitialJobs,
  dedupeIdenticalChannelRefs,
  runCompetitorLoadPool,
  type ChannelLoadJob,
} from "@/lib/competitor-multi-load";
import { Disclosure } from "@/components/design-system";
import { formatUserChannelRefLabel, resolveChannelDisplayName } from "@/lib/competitor-multi-display";
import { competitorPreviewErrorFromUnknown } from "@/lib/competitor-multi-errors";
import { cn, formatCompactNumber, parseChannelRefs } from "@/lib/utils";

export function CompetitorMultiHome() {
  const [rawInput, setRawInput] = useState("");
  const [jobs, setJobs] = useState<ChannelLoadJob[]>([]);
  const [runActive, setRunActive] = useState(false);
  const [feedSort, setFeedSort] = useState<RegularSortMode>("newest");
  const [channelFilter, setChannelFilter] = useState<string>("all");

  const generationRef = useRef(0);
  const jobGenerationRef = useRef<Map<string, number>>(new Map());
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());

  const parsedRefs = parseChannelRefs(rawInput);
  const uniqueInputRefs = dedupeIdenticalChannelRefs(parsedRefs);
  const count = uniqueInputRefs.length;
  const isValidCount = count >= COMPETITOR_MIN_CHANNELS && count <= COMPETITOR_MAX_CHANNELS;

  const uniqueChannels = useMemo(() => buildUniqueChannelViews(jobs), [jobs]);

  const allRegularFeed = useMemo(() => {
    const pubs = uniqueChannels.flatMap((ch) =>
      ch.publications.map((p) => ({
        ...p,
        channel_id: p.channel_id || ch.channelId,
        _channelTitle: ch.displayTitle,
      })),
    );
    const filtered =
      channelFilter === "all"
        ? pubs
        : pubs.filter((p) => (p.channel_id || "") === channelFilter);
    return sortRegularPublicationsUnknownLast(filtered, feedSort);
  }, [uniqueChannels, channelFilter, feedSort]);

  const uniqueChannelCount = uniqueChannels.length;
  const showSingleChannelNote =
    count >= COMPETITOR_MIN_CHANNELS && uniqueChannelCount === 1 && jobs.some((j) => j.response);

  const loadOne = useCallback(async (inputRef: string, signal: AbortSignal) => {
    return fetchCompetitorChannelPreview({ input_ref: inputRef, channel_ref: inputRef }, signal);
  }, []);

  const startPool = useCallback(
    async (inputRefs: string[], generation: number) => {
      await runCompetitorLoadPool({
        inputRefs,
        generation,
        isGenerationCurrent: (g) => g === generationRef.current,
        getJobGeneration: (inputRef) => jobGenerationRef.current.get(inputRef) ?? 0,
        abortControllers: abortControllersRef.current,
        fetchOne: loadOne,
        onJobStart: (inputRef) => {
          setJobs((prev) =>
            prev.map((j) =>
              j.inputRef === inputRef
                ? { ...j, status: "loading", errorMessage: null, userError: null }
                : j,
            ),
          );
        },
        onJobSuccess: (inputRef, response) => {
          setJobs((prev) => applyChannelPreviewSuccess(prev, inputRef, response));
        },
        onJobError: (inputRef, userError, aborted) => {
          if (aborted) {
            return;
          }
          console.error("[competitor-multi] channel load failed", {
            inputRef,
            kind: userError.kind,
            detail: userError.technicalDetail,
          });
          setJobs((prev) => {
            const job = prev.find((j) => j.inputRef === inputRef);
            const keep = Boolean(job?.response);
            const status = keep ? job!.status : "error";
            return applyChannelPreviewError(prev, inputRef, userError, keep).map((j) =>
              j.inputRef === inputRef && keep ? { ...j, status } : j,
            );
          });
        },
      });
    },
    [loadOne],
  );

  const handleRun = async () => {
    if (!isValidCount) {
      return;
    }
    for (const controller of abortControllersRef.current.values()) {
      controller.abort();
    }
    abortControllersRef.current.clear();

    const generation = ++generationRef.current;
    const refs = uniqueInputRefs;
    jobGenerationRef.current = new Map(refs.map((r) => [r, generation]));
    setJobs(createInitialJobs(refs));
    setRunActive(true);
    setChannelFilter("all");

    try {
      await startPool(refs, generation);
    } finally {
      if (generation === generationRef.current) {
        setRunActive(false);
      }
    }
  };

  const retryChannel = async (inputRef: string) => {
    const generation = generationRef.current;
    const retryGen = (jobGenerationRef.current.get(inputRef) ?? generation) + 1;
    jobGenerationRef.current.set(inputRef, retryGen);

    const existing = jobs.find((j) => j.inputRef === inputRef);
    const keepResponse = Boolean(existing?.response);

    setJobs((prev) =>
      prev.map((j) =>
        j.inputRef === inputRef
          ? { ...j, status: "loading", retryLoading: true, errorMessage: null, userError: null }
          : j,
      ),
    );

    const controller = new AbortController();
    abortControllersRef.current.set(inputRef, controller);

    try {
      const response = await loadOne(inputRef, controller.signal);
      if (jobGenerationRef.current.get(inputRef) !== retryGen) {
        return;
      }
      setJobs((prev) => applyChannelPreviewSuccess(prev, inputRef, response));
    } catch (err) {
      const aborted = controller.signal.aborted;
      if (aborted || jobGenerationRef.current.get(inputRef) !== retryGen) {
        return;
      }
      const userError = competitorPreviewErrorFromUnknown(err);
      console.error("[competitor-multi] channel retry failed", {
        inputRef,
        kind: userError.kind,
        detail: userError.technicalDetail,
      });
      setJobs((prev) => applyChannelPreviewError(prev, inputRef, userError, keepResponse));
    } finally {
      abortControllersRef.current.delete(inputRef);
      setJobs((prev) =>
        prev.map((j) => (j.inputRef === inputRef ? { ...j, retryLoading: false } : j)),
      );
    }
  };

  const failedJobs = jobs.filter(
    (j) => j.status === "error" && !j.mergedIntoChannelId,
  );

  const loadingChannelJobs = jobs.filter(
    (j) =>
      !j.mergedIntoChannelId &&
      !j.response &&
      (j.status === "queued" || j.status === "loading"),
  );

  return (
    <>
      <header>
        <div className="flex items-center gap-2">
          <Users className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight">Обзор конкурентов</h1>
        </div>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          До пяти каналов — последние публикации в одной ленте для поиска идей. Это ограниченная
          выборка вкладки Videos; сортировка по просмотрам не является рейтингом каналов.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Каналы конкурентов</CardTitle>
          <CardDescription>
            От {COMPETITOR_MIN_CHANNELS} до {COMPETITOR_MAX_CHANNELS} ссылок (URL, @handle или UC…).
            Уникальных строк: {count}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            placeholder={`https://youtube.com/@channel1\n@channel2\nUCxxxxxxxxxxxxxxxx`}
            value={rawInput}
            onChange={(e) => setRawInput(e.target.value)}
            rows={8}
            className="font-mono text-xs"
          />
          {count > 0 && !isValidCount ? (
            <p className="text-sm text-amber-400">
              Нужно от {COMPETITOR_MIN_CHANNELS} до {COMPETITOR_MAX_CHANNELS} каналов (сейчас{" "}
              {count}).
            </p>
          ) : null}
          <Button
            type="button"
            onClick={() => void handleRun()}
            disabled={runActive || !isValidCount}
            className="gap-2"
          >
            <Play className="h-4 w-4" />
            {runActive ? "Загружаем…" : "Загрузить обзор"}
          </Button>
        </CardContent>
      </Card>

      {showSingleChannelNote ? (
        <StateMessage
          title="Один уникальный канал"
          description="Все введённые ссылки относятся к одному каналу — показан один блок и общая лента без дублей."
        />
      ) : null}

      {uniqueChannels.length > 0 ? (
        <section className="space-y-4">
          <h2 className="text-base font-semibold">Каналы</h2>
          <div className="grid gap-4 lg:grid-cols-2">
            {uniqueChannels.map((ch) => {
              const period = samplePeriodLabel(ch.periodSourcePubs);
              return (
                <Card key={ch.channelId}>
                  <CardContent className="flex gap-3 p-4">
                    {ch.avatarUrl ? (
                      <Image
                        src={ch.avatarUrl}
                        alt=""
                        width={48}
                        height={48}
                        unoptimized
                        className="h-12 w-12 rounded-full object-cover ring-1 ring-border/60"
                      />
                    ) : null}
                    <div className="min-w-0 flex-1 space-y-1 text-sm">
                      <p className="truncate font-semibold">{ch.displayTitle}</p>
                      {ch.subscribersCount != null && ch.subscribersCount > 0 ? (
                        <p className="text-muted-foreground">
                          {formatCompactNumber(ch.subscribersCount)} подписчиков
                        </p>
                      ) : null}
                      <p className="text-xs text-muted-foreground">
                        Загружено {ch.feedLoadedCount}; подтверждено regular:{" "}
                        {ch.regularConfirmedCount}
                        {period ? ` · период ${period}` : ""}
                      </p>
                      {ch.loadStatus === "partial" && ch.enrichmentError ? (
                        <p className="text-xs text-amber-600 dark:text-amber-500">
                          Частичные данные: {ch.enrichmentError}
                        </p>
                      ) : null}
                      {ch.loadStatus === "partial" ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="mt-2 gap-1"
                          disabled={jobs.some(
                            (j) => j.inputRef === ch.aliasInputRefs[0] && j.retryLoading,
                          )}
                          onClick={() => void retryChannel(ch.aliasInputRefs[0])}
                        >
                          <RefreshCw className="h-3 w-3" />
                          Повторить загрузку
                        </Button>
                      ) : null}
                      {ch.aliasInputRefs.length > 1 ? (
                        <p className="text-xs text-muted-foreground">
                          Объединено ссылок: {ch.aliasInputRefs.length}
                        </p>
                      ) : null}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
            {loadingChannelJobs.map((job) => {
              const label = resolveChannelDisplayName({
                channelTitle: "",
                channelId: "",
                inputRefs: [job.inputRef],
                loading: true,
              });
              return (
                <Card key={`loading-${job.inputRef}`} className="border-dashed">
                  <CardContent className="p-4 text-sm">
                    <p className="font-semibold">{label}</p>
                    <p className="text-muted-foreground">Загружаем канал…</p>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </section>
      ) : null}

      {uniqueChannels.length === 0 && loadingChannelJobs.length > 0 ? (
        <section className="space-y-4">
          <h2 className="text-base font-semibold">Каналы</h2>
          <div className="grid gap-4 lg:grid-cols-2">
            {loadingChannelJobs.map((job) => {
              const label = resolveChannelDisplayName({
                channelTitle: "",
                channelId: "",
                inputRefs: [job.inputRef],
                loading: true,
              });
              return (
                <Card key={`loading-only-${job.inputRef}`} className="border-dashed">
                  <CardContent className="p-4 text-sm">
                    <p className="font-semibold">{label}</p>
                    <p className="text-muted-foreground">Загружаем канал…</p>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </section>
      ) : null}

      {failedJobs.map((job) => {
        const refLabel = formatUserChannelRefLabel(job.inputRef);
        const userErr = job.userError;
        const title = userErr?.title ?? "Не удалось загрузить канал";
        const description =
          userErr?.description ??
          "Попробуйте ещё раз. Если ошибка повторяется, проверьте адрес канала.";
        return (
          <div key={job.inputRef} className="space-y-2">
            <StateMessage
              variant="error"
              title={`${title}: ${refLabel}`}
              description={description}
            />
            {userErr?.technicalDetail ? (
              <Disclosure summary="Технические сведения">
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all text-xs text-muted-foreground">
                  {userErr.technicalDetail}
                </pre>
              </Disclosure>
            ) : null}
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1"
              disabled={job.retryLoading}
              onClick={() => void retryChannel(job.inputRef)}
            >
              <RefreshCw className="h-3 w-3" />
              Повторить
            </Button>
          </div>
        );
      })}

      {allRegularFeed.length > 0 ? (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-base font-semibold">Обычные видео</h2>
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="rounded-md border border-border/60 bg-background px-2 py-1 text-sm"
                value={channelFilter}
                onChange={(e) => setChannelFilter(e.target.value)}
              >
                <option value="all">Все каналы</option>
                {uniqueChannels.map((ch) => (
                  <option key={ch.channelId} value={ch.channelId}>
                    {ch.displayTitle}
                  </option>
                ))}
              </select>
              <div className="flex rounded-md border border-border/60 p-0.5 text-sm">
                <button
                  type="button"
                  className={cn("rounded px-3 py-1", feedSort === "newest" && "bg-muted font-medium")}
                  onClick={() => setFeedSort("newest")}
                >
                  Новые
                </button>
                <button
                  type="button"
                  className={cn(
                    "rounded px-3 py-1",
                    feedSort === "most_views" && "bg-muted font-medium",
                  )}
                  onClick={() => setFeedSort("most_views")}
                >
                  Больше просмотров
                </button>
              </div>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {allRegularFeed.map((pub) => (
              <CompetitorPublicationCard
                key={`${pub.channel_id}-${pub.video_id}`}
                pub={pub}
                channelTitle={(pub as { _channelTitle?: string })._channelTitle || pub.channel_id || ""}
              />
            ))}
          </div>
        </section>
      ) : null}

      {jobs.length > 0 &&
      !runActive &&
      allRegularFeed.length === 0 &&
      uniqueChannels.every((c) => c.regularConfirmedCount === 0) ? (
        <StateMessage
          title="Нет подтверждённых обычных видео"
          description="Shorts, трансляции и ролики без метаданных не попадают в основную ленту."
        />
      ) : null}
    </>
  );
}
