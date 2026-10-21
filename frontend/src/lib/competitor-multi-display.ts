/** User-visible labels for competitor multi-channel overview (COMP-06/07). */

const UC_ID = /^UC[\w-]{10,}$/;

export function shortChannelId(channelId: string): string {
  if (channelId.length <= 12) return channelId;
  return `…${channelId.slice(-8)}`;
}

/** Readable label from what the user typed (never raw API URL in titles). */
export function formatUserChannelRefLabel(inputRef: string): string {
  const t = inputRef.trim();
  if (!t) return "Канал";
  if (t.startsWith("@")) return t;
  const withScheme = t.startsWith("http://") || t.startsWith("https://") ? t : `https://${t}`;
  try {
    const url = new URL(withScheme);
    const handle = url.pathname.match(/\/@([^/]+)/)?.[1];
    if (handle) return `@${handle}`;
    const cid = url.pathname.match(/\/channel\/(UC[^/]+)/)?.[1];
    if (cid) return `Канал ${shortChannelId(cid)}`;
  } catch {
    /* not a URL */
  }
  if (UC_ID.test(t)) return `Канал ${shortChannelId(t)}`;
  if (t.length > 56) return `${t.slice(0, 53)}…`;
  return t;
}

function isPlaceholderTitle(title: string, channelId: string): boolean {
  const trimmed = title.trim();
  if (!trimmed) return true;
  if (trimmed === channelId) return true;
  if (UC_ID.test(trimmed) && trimmed === channelId) return true;
  return false;
}

/** Title for filter, cards, and video attribution. */
export function resolveChannelDisplayName(params: {
  channelTitle: string;
  channelId: string;
  inputRefs: string[];
  loading?: boolean;
}): string {
  if (params.loading) {
    const ref = params.inputRefs[0];
    return ref ? formatUserChannelRefLabel(ref) : "Загружаем канал…";
  }
  const title = params.channelTitle?.trim() ?? "";
  if (!isPlaceholderTitle(title, params.channelId)) {
    return title;
  }
  for (const ref of params.inputRefs) {
    const label = formatUserChannelRefLabel(ref);
    if (!UC_ID.test(label.replace(/^Канал /, ""))) {
      return label;
    }
  }
  if (params.inputRefs[0]) {
    return formatUserChannelRefLabel(params.inputRefs[0]);
  }
  return title || `Канал ${shortChannelId(params.channelId)}`;
}

export type CompetitorPreviewErrorKind =
  | "invalid_input"
  | "channel_not_found"
  | "youtube_unavailable"
  | "backend_unavailable"
  | "unknown";

export type CompetitorPreviewUserError = {
  kind: CompetitorPreviewErrorKind;
  title: string;
  description: string;
  technicalDetail: string;
};

export function mapCompetitorPreviewError(
  rawMessage: string,
  httpStatus?: number,
): CompetitorPreviewUserError {
  const technicalDetail = rawMessage.trim() || "Неизвестная ошибка";
  const lower = technicalDetail.toLowerCase();

  if (
    lower.includes("channel not found") ||
    lower.includes("not found for url") ||
    lower.includes("cannot resolve channel") ||
    lower.includes("videos tab not found") ||
    (httpStatus === 422 && lower.includes("не найден"))
  ) {
    return {
      kind: "channel_not_found",
      title: "Канал не найден",
      description:
        "YouTube не вернул этот канал. Проверьте опечатку в @handle или что канал существует и доступен.",
      technicalDetail,
    };
  }
  if (
    httpStatus === 422 ||
    lower.includes("unsupported channel identifier") ||
    lower.includes("укажите channel") ||
    lower.includes("некоррект")
  ) {
    return {
      kind: "invalid_input",
      title: "Не удалось распознать адрес канала",
      description:
        "Проверьте ссылку, @handle или ID канала (UC…). Используйте публичный канал YouTube.",
      technicalDetail,
    };
  }
  if (
    httpStatus === 502 ||
    lower.includes("youtube") ||
    lower.includes("innertube") ||
    lower.includes("quota")
  ) {
    return {
      kind: "youtube_unavailable",
      title: "Временная ошибка YouTube",
      description:
        "Данные с YouTube сейчас недоступны. Подождите немного и нажмите «Повторить».",
      technicalDetail,
    };
  }
  if (
    httpStatus === 503 ||
    httpStatus === 504 ||
    httpStatus === 0 ||
    lower.includes("network error") ||
    lower.includes("econnrefused") ||
    lower.includes("timeout")
  ) {
    return {
      kind: "backend_unavailable",
      title: "Сервис анализа недоступен",
      description:
        "Не удалось связаться с сервером. Убедитесь, что backend запущен, и повторите попытку.",
      technicalDetail,
    };
  }
  return {
    kind: "unknown",
    title: "Не удалось загрузить канал",
    description: "Попробуйте ещё раз. Если ошибка повторяется, проверьте адрес канала.",
    technicalDetail,
  };
}
