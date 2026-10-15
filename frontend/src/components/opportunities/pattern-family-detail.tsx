"use client";



import { useCallback, useEffect, useMemo, useState } from "react";

import Link from "next/link";

import { ArrowLeft } from "lucide-react";



import {

  ErrorState,

  LoadingState,

  PageShell,

  SectionPanel,

  UnavailableState,

} from "@/components/design-system";

import { buttonVariants } from "@/components/ui/button";

import { Input } from "@/components/ui/input";

import { patternActivity, patternDetailHref, snapshotFreshnessLabel } from "@/lib/attention-format";

import {

  familyDetailHeadline,

  familyDetailSearchDisclaimer,

  familyMergedPatternsSectionDescription,

  familyMergedPatternsSectionTitle,

  familyRelatedKeywordsSectionDescription,

  familyRelatedKeywordsSectionTitle,

  familySnapshotMetaLine,

  familyVideoListSectionDescription,

  familyVideoListSectionTitle,

  familyWhyTogetherLead,

} from "@/lib/family-detail-copy";

import {

  familyDiagnosticIntro,

  humanizeGroupingReason,

  humanizeQualityFlag,

  humanizeSupportSource,

} from "@/lib/family-diagnostic-copy";

import type { AttentionPatternFamilyDetailResponse } from "@/lib/attention-types";

import { getAttentionPatternFamilyDetail } from "@/lib/api";

import { isSearchCollectionFamily } from "@/lib/opportunity-family-presentation";

import { surfaces } from "@/lib/design-system/layout";

import { SaveFamilyButton } from "@/components/saved-research/save-family-button";

import { cn } from "@/lib/utils";



import { FamilyMemberCard } from "./family-member-card";



export function PatternFamilyDetailView({ familyKey }: { familyKey: string }) {

  const [state, setState] = useState<"loading" | "error" | "ready">("loading");

  const [message, setMessage] = useState("");

  const [detail, setDetail] =

    useState<AttentionPatternFamilyDetailResponse | null>(null);

  const [channelFilter, setChannelFilter] = useState("all");

  const [winnerFilter, setWinnerFilter] = useState<"all" | "winners" | "rest">(

    "all",

  );

  const [query, setQuery] = useState("");



  const load = useCallback(async () => {

    setState("loading");

    try {

      const data = await getAttentionPatternFamilyDetail(familyKey);

      setDetail(data);

      setState("ready");

    } catch (error) {

      setMessage(

        error instanceof Error ? error.message : "Семейство не найдено",

      );

      setState("error");

    }

  }, [familyKey]);



  useEffect(() => {

    void load();

  }, [load]);



  const feedWinnerIds = useMemo(

    () => new Set(detail?.family?.feed_winner_video_ids ?? []),

    [detail?.family?.feed_winner_video_ids],

  );



  const videos = useMemo(() => {

    const items = detail?.videos ?? [];

    const q = query.trim().toLowerCase();

    return items.filter((row) => {

      if (channelFilter !== "all" && row.channel_id !== channelFilter) {

        return false;

      }

      if (winnerFilter === "winners" && !row.in_winner_snapshot) {

        return false;

      }

      if (winnerFilter === "rest" && row.in_winner_snapshot) {

        return false;

      }

      if (!q) {

        return true;

      }

      return (

        row.title.toLowerCase().includes(q) ||

        row.channel_title.toLowerCase().includes(q) ||

        row.video_id.toLowerCase().includes(q)

      );

    });

  }, [detail, channelFilter, winnerFilter, query]);



  if (state === "loading") {

    return (

      <PageShell>

        <LoadingState title="Загрузка подборки…" />

      </PageShell>

    );

  }

  if (state === "error") {

    return (

      <PageShell>

        <ErrorState

          title="Не удалось открыть подборку"

          description={message}

          onRetry={load}

        />

      </PageShell>

    );

  }

  if (!detail?.family || detail.data_source === "unavailable") {

    return (

      <PageShell>

        <UnavailableState title="Attention Engine ещё не рассчитан." />

      </PageShell>

    );

  }



  const family = detail.family;

  const activity = patternActivity(family);

  const headline = familyDetailHeadline(family, detail.related_keywords);

  const winnerInFeedCount = family.feed_winner_video_ids.length;



  return (

    <PageShell>

      <Link

        href="/opportunities"

        className={cn(

          buttonVariants({ variant: "ghost", size: "sm" }),

          "w-fit",

        )}

      >

        <ArrowLeft className="h-4 w-4" />К возможностям

      </Link>



      <header className="space-y-3" data-testid="family-detail-header">

        <h1 className="text-2xl font-semibold tracking-tight">{headline}</h1>

        {isSearchCollectionFamily(family) ? (

          <p className="max-w-3xl text-sm text-muted-foreground">

            {familyDetailSearchDisclaimer()}

          </p>

        ) : (

          <p className="max-w-3xl text-sm text-muted-foreground">

            {familyWhyTogetherLead(family)}

          </p>

        )}

        <dl className="grid gap-3 sm:grid-cols-3">

          <div className={cn(surfaces.sectionMuted, "rounded-lg p-3")}>

            <dt className="text-xs text-muted-foreground">Видео в подборке</dt>

            <dd className="text-xl font-semibold tabular-nums">{family.video_count}</dd>

            <dd className="text-[11px] text-muted-foreground">

              Уникальные video_id в снимке Attention

            </dd>

          </div>

          <div

            className={cn(surfaces.sectionMuted, "rounded-lg p-3")}

            data-testid="pattern-channel-diversity"

          >

            <dt className="text-xs text-muted-foreground">Независимых каналов</dt>

            <dd className="text-xl font-semibold tabular-nums">{family.channel_count}</dd>

            <dd className="text-[11px] text-muted-foreground">На момент группировки</dd>

          </div>

          <div

            className={cn(surfaces.sectionMuted, "rounded-lg p-3")}

            data-testid="family-detail-feed-winners"

          >

            <dt className="text-xs text-muted-foreground">В ленте Winners</dt>

            <dd className="text-xl font-semibold tabular-nums">{winnerInFeedCount}</dd>

            <dd className="text-[11px] text-muted-foreground">

              Из этого run, не «успешных» по запросу

            </dd>

          </div>

        </dl>

        <p

          className="text-xs text-muted-foreground"

          data-testid="family-snapshot-meta"

        >

          {familySnapshotMetaLine(detail.computed_at, detail.run_id)} ·{" "}

          {snapshotFreshnessLabel(detail.computed_at)}

        </p>

        <SaveFamilyButton familyKey={family.family_key} runId={detail.run_id} />

      </header>



      <SectionPanel

        title={familyVideoListSectionTitle(family)}

        description={familyVideoListSectionDescription(family)}

      >

        <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center">

          <Input

            value={query}

            onChange={(event) => setQuery(event.target.value)}

            placeholder="Поиск по названию или каналу"

            aria-label="Поиск по названию или каналу"

            className="max-w-xs"

          />

          <label className="text-sm text-muted-foreground">

            Канал{" "}

            <select

              className="rounded-md border border-input bg-transparent px-2 py-1 text-foreground"

              value={channelFilter}

              onChange={(event) => setChannelFilter(event.target.value)}

            >

              <option value="all">Все</option>

              {detail.channels.map((channel) => (

                <option key={channel.channel_id} value={channel.channel_id}>

                  {channel.channel_title}

                </option>

              ))}

            </select>

          </label>

          <label className="text-sm text-muted-foreground">

            Сигнал Winners{" "}

            <select

              className="rounded-md border border-input bg-transparent px-2 py-1 text-foreground"

              value={winnerFilter}

              onChange={(event) =>

                setWinnerFilter(event.target.value as "all" | "winners" | "rest")

              }

            >

              <option value="all">Все ролики</option>

              <option value="winners">Только Winners run</option>

              <option value="rest">Без сигнала Winners</option>

            </select>

          </label>

        </div>

        <p className="text-xs text-muted-foreground" aria-live="polite">

          Показано {videos.length} из {detail.videos.length} · порядок снимка

          Attention

        </p>

        <div

          className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"

          data-testid="family-member-list"

        >

          {videos.map((row) => (

            <FamilyMemberCard

              key={row.video_id}

              video={row}

              snapshotComputedAt={detail.computed_at}

              highlightFeedWinner={feedWinnerIds.has(row.video_id)}

            />

          ))}

        </div>

      </SectionPanel>



      <details

        className={cn(surfaces.section, "rounded-xl p-4 text-sm")}

        data-testid="family-formation-details"

      >

        <summary className="cursor-pointer font-medium">

          Как сформирована подборка

        </summary>

        <div className="mt-4 space-y-4 text-muted-foreground">

          <p>{familyDiagnosticIntro(family)}</p>

          <p data-testid="family-tier-reason">{familyWhyTogetherLead(family)}</p>

          {family.tier_reason ? (

            <p className="text-xs">{family.tier_reason}</p>

          ) : null}



          <div>

            <p className="font-medium text-foreground">

              {familyRelatedKeywordsSectionTitle()}

            </p>

            <p className="text-xs">{familyRelatedKeywordsSectionDescription()}</p>

            {detail.related_keywords.length === 0 ? (

              <p className="mt-1 text-xs">keyword_id в снимке не указаны.</p>

            ) : (

              <ul className="mt-2 flex flex-wrap gap-2">

                {detail.related_keywords.map((row) => (

                  <li

                    key={row.keyword_id}

                    className="rounded-full border border-border/60 px-3 py-1 text-xs text-foreground"

                  >

                    {row.keyword}{" "}

                    <span className="font-mono text-muted-foreground">

                      #{row.keyword_id}

                    </span>

                  </li>

                ))}

              </ul>

            )}

          </div>



          <div>

            <p className="font-medium text-foreground">

              {familyMergedPatternsSectionTitle(family)}

            </p>

            <p className="text-xs">{familyMergedPatternsSectionDescription(family)}</p>

            <ul className="mt-2 space-y-1" data-testid="family-member-patterns">

              {family.member_pattern_keys.map((key, index) => (

                <li key={key}>

                  <Link href={patternDetailHref(key)} className="text-primary hover:underline">

                    {family.member_labels[index] ?? key}

                  </Link>

                </li>

              ))}

            </ul>

          </div>



          {family.quality_flags.length > 0 ? (

            <div data-testid="family-flags">

              <p className="font-medium text-foreground">Предупреждения качества</p>

              <ul className="mt-1 list-disc pl-4 text-xs">

                {family.quality_flags.map((flag) => (

                  <li key={flag}>

                    <span className="font-mono text-[10px]">{flag}</span> —{" "}

                    {humanizeQualityFlag(flag)}

                  </li>

                ))}

              </ul>

            </div>

          ) : null}



          {family.grouping_reasons.length > 0 ? (

            <div>

              <p className="font-medium text-foreground">Основания объединения</p>

              <ul className="mt-1 list-disc pl-4 text-xs">

                {family.grouping_reasons.map((reason) => (

                  <li key={reason}>

                    <span className="font-mono text-[10px]">{reason}</span> —{" "}

                    {humanizeGroupingReason(reason)}

                  </li>

                ))}

              </ul>

            </div>

          ) : null}



          {family.support_sources.length > 0 ? (

            <div data-testid="family-support">

              <p className="font-medium text-foreground">Источники поддержки группы</p>

              <ul className="mt-1 list-disc pl-4 text-xs">

                {family.support_sources.map((source) => (

                  <li key={source}>

                    <span className="font-mono text-[10px]">{source}</span> —{" "}

                    {humanizeSupportSource(source)}

                  </li>

                ))}

              </ul>

            </div>

          ) : null}



          <div data-testid="pattern-activity">

            <p className="font-medium text-foreground">

              История появления видео в группе (UTC-окна Attention)

            </p>

            <p className="text-xs">

              Счётчики новых участников по периодам снимка — не текущие просмотры

              роликов ниже.

            </p>

            <p className="mt-1 text-foreground">

              {activity.available ? activity.label : "Недостаточно истории в снимке"}

            </p>

          </div>



          {detail.channels.length > 0 ? (

            <div>

              <p className="font-medium text-foreground">Каналы в подборке</p>

              <ul className="mt-1 grid gap-1 sm:grid-cols-2 text-xs">

                {detail.channels.map((channel) => (

                  <li key={channel.channel_id}>

                    {channel.channel_title}{" "}

                    <span className="text-muted-foreground">

                      ({channel.video_count} видео)

                    </span>

                  </li>

                ))}

              </ul>

            </div>

          ) : null}



          <div className="border-t border-border/60 pt-3 font-mono text-[11px]">

            <p className="mb-2 font-sans text-xs font-medium text-foreground">

              Технические идентификаторы (заморожены в run)

            </p>

            <div>family_key: {family.family_key}</div>

            <div>family_kind: {family.family_kind}</div>

            <div>grouping_basis_kind: {family.grouping_basis_kind}</div>

            <div>run_id: {detail.run_id ?? "—"}</div>

            <div>

              keyword_ids:{" "}

              {family.participating_keyword_ids.length

                ? family.participating_keyword_ids.join(", ")

                : "—"}

            </div>

            <div>

              frozen video_ids ({family.participating_video_ids.length}):{" "}

              {family.participating_video_ids.slice(0, 8).join(", ")}

              {family.participating_video_ids.length > 8 ? " …" : ""}

            </div>

            <div>

              breakout_eligible_count (диагностика, не успех):{" "}

              {family.breakout_eligible_count}

            </div>

          </div>

        </div>

      </details>

    </PageShell>

  );

}

