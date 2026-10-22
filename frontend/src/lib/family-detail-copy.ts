import type { AttentionPatternFamily } from "@/lib/attention-types";
import type { AttentionRelatedKeyword } from "@/lib/attention-types";
import { isSearchCollectionFamily } from "@/lib/opportunity-family-presentation";

import { formatSnapshotUtcDay } from "@/lib/family-member-metrics";

export function familyDetailHeadline(
  family: AttentionPatternFamily,
  relatedKeywords: AttentionRelatedKeyword[],
): string {
  if (isSearchCollectionFamily(family)) {
    const query =
      relatedKeywords[0]?.keyword?.trim() ||
      family.label?.trim() ||
      "поисковый запрос";
    return `Подборка по поисковому запросу «${query}»`;
  }
  return family.label?.trim() || "Группа возможностей";
}

export function familyDetailSearchDisclaimer(): string {
  return (
    "Видео найдены по общему запросу или пересечению в снимке Radar; " +
    "это не означает, что у них один формат, одна игра или один сценарий."
  );
}

export function familySnapshotMetaLine(
  computedAt: string | null,
  runId: string | null,
): string {
  const day = formatSnapshotUtcDay(computedAt);
  const run = runId ? ` · run ${runId.slice(0, 12)}…` : "";
  return `Снимок Attention · UTC ${day}${run}`;
}

export function familyVideoListSectionTitle(family: AttentionPatternFamily): string {
  return "Ролики подборки для ручного сравнения";
}

export function familyVideoListSectionDescription(family: AttentionPatternFamily): string {
  if (isSearchCollectionFamily(family)) {
    return (
      "Порядок как в снимке Attention. Ролики с бейджем Winner уже в ленте Radar этого run — " +
      "их удобнее открыть для разведки; остальные участники того же запроса без сигнала Winners."
    );
  }
  return (
    "Полный список участников группы для ручной проверки. " +
    "Сходство заголовков или запросов — повод сравнить ролики, а не доказательство повторяемости."
  );
}

export function familyRelatedKeywordsSectionTitle(): string {
  return "Запросы подборки (источник поиска)";
}

export function familyRelatedKeywordsSectionDescription(): string {
  return (
    "Эти TargetKeyword свели видео в одну группу в Radar. " +
    "Запрос объясняет, откуда пришли ролики, а не тему каждого видео."
  );
}

export function familyMergedPatternsSectionTitle(family: AttentionPatternFamily): string {
  if (isSearchCollectionFamily(family)) {
    return "Пересечение групп по запросам и видео";
  }
  return "Связанные исходные группы";
}

export function familyMergedPatternsSectionDescription(family: AttentionPatternFamily): string {
  if (isSearchCollectionFamily(family)) {
    return (
      "Подборка собрана из нескольких паттернов с общими keyword_id или video_id. " +
      "Это не подтверждённое сходство формата — только техническое пересечение в снимке Attention."
    );
  }
  return (
    "Исходные паттерны, объединённые в это семейство. " +
    "Откройте группу, чтобы увидеть её состав; совпадение не гарантирует одинаковую идею."
  );
}

export function familyWhyTogetherLead(family: AttentionPatternFamily): string {
  if (isSearchCollectionFamily(family)) {
    return (
      "Видео оказались вместе, потому что Radar нашёл их по одному или нескольким " +
      "связанным поисковым запросам (или по метаданным темы). Это не повторяемый формат."
    );
  }
  return family.tier_reason || "Сравните ролики вручную перед выводами о повторяемости.";
}
