import type { AttentionPatternFamily } from "@/lib/attention-types";

export function humanizeQualityFlag(flag: string): string {
  switch (flag) {
    case "keyword_only":
      return "Группа держится только на общем keyword_id — тема каждого ролика не проверялась.";
    case "broad_keyword_group":
      return "Запрос широкий: в одной подборке могут быть разные игры, форматы и каналы.";
    case "title_phrase_evidence":
      return "Есть пересечение по фразам в названиях — это слабее, чем общий запрос.";
    case "needs_manual_review":
      return "Radar пометил группу как требующую ручной проверки перед выводами.";
    default:
      return flag.replace(/_/g, " ");
  }
}

export function humanizeGroupingReason(reason: string): string {
  switch (reason) {
    case "shared_video_membership":
      return "Один и тот же video_id встретился в нескольких паттернах снимка.";
    case "shared_keyword_membership":
      return "Видео связаны через один или несколько keyword_id в Discovery.";
    case "metadata_topic_cluster":
      return "Объединение по метаданным темы (не по формату ролика).";
    case "title_phrase_overlap":
      return "Пересечение по фразе в заголовках — не доказательство одной идеи.";
    default:
      return reason.replace(/_/g, " ");
  }
}

export function humanizeSupportSource(source: string): string {
  switch (source) {
    case "keyword":
      return "Источник: поисковый запрос TargetKeyword.";
    case "video_topic":
      return "Источник: метаданные темы видео.";
    case "title_phrase":
      return "Источник: повторяющаяся фраза в названии.";
    default:
      return source.replace(/_/g, " ");
  }
}

export function familyDiagnosticIntro(family: AttentionPatternFamily): string {
  if (family.opportunity_presentation_tier === "search_collection") {
    return (
      "Radar собрал эту подборку из паттернов текущего снимка Attention. " +
      "Общий запрос или пересечение keyword_id не означает один формат, одну игру или повторяемый успех."
    );
  }
  return (
    "Ниже — технические основания объединения в снимке Attention. " +
    "Они помогают понять происхождение группы, но не заменяют ручной просмотр роликов."
  );
}
