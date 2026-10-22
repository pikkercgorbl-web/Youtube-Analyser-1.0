import Link from "next/link";

import { YoutubeThumb } from "@/components/opportunities/youtube-thumb";
import type { ResearchPortfolioSavedItem } from "@/lib/validation-types";
import { formatValidationInstant } from "@/lib/validation-presentation";
import { APP_TIMEZONE } from "@/lib/app-timezone";
import {
  type ValidationPeriodDates,
  savedItemHrefWithReturn,
} from "@/lib/validation-period";

function statusLabel(status: string, labels: Record<string, string>): string {
  if (status === "ARCHIVED") return "В архиве";
  return labels[status] ?? status;
}

function savedAtLabel(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("ru-RU", { timeZone: APP_TIMEZONE });
}

export function ValidationSavedItemRow({
  item,
  dates,
  statusLabels,
}: {
  item: ResearchPortfolioSavedItem;
  dates: ValidationPeriodDates;
  statusLabels: Record<string, string>;
}) {
  const measurementLine =
    item.observation_count > 0 && item.latest_observed_at
      ? `Последнее наблюдение: ${formatValidationInstant(item.latest_observed_at)} (${APP_TIMEZONE})`
      : item.observation_count > 0
        ? `Наблюдений: ${item.observation_count}`
        : "Измерений пока нет";

  return (
    <li className="flex gap-3 rounded-xl border border-border p-3 sm:items-center">
      {item.kind === "video" && item.video_id ? (
        <div className="h-[54px] w-24 shrink-0 overflow-hidden rounded-md">
          <YoutubeThumb
            videoId={item.video_id}
            title={item.title}
            compact
            className="aspect-video h-full w-full"
          />
        </div>
      ) : null}
      <div className="min-w-0 flex-1">
        <Link
          href={savedItemHrefWithReturn(item, dates)}
          className="font-medium hover:text-primary line-clamp-2"
        >
          {item.title}
        </Link>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {item.kind === "video" ? "Видео" : "Тема"} · сохранено {savedAtLabel(item.saved_at)}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">{measurementLine}</p>
      </div>
      <div className="shrink-0 text-right text-xs text-muted-foreground sm:max-w-[9rem]">
        <p>Ваш статус: {statusLabel(item.current_status, statusLabels)}</p>
        {item.has_latest_feedback ? <p className="mt-0.5">Есть оценка находки</p> : null}
      </div>
    </li>
  );
}
