import type { SavedFamilyListItem } from "./saved-research-types";
import { OBSERVATION_SOURCE_LABELS } from "./saved-research-labels";

export function formatMeasurementSource(source: string | null | undefined): string {
  if (!source) return "—";
  return OBSERVATION_SOURCE_LABELS[source] ?? source;
}

export function formatFamilyCountLine(row: SavedFamilyListItem): string {
  const frozenV = row.frozen_video_count;
  const currentV = row.current_video_count;
  const frozenC = row.frozen_channel_count;
  const currentC = row.current_channel_count;

  let videoPart = "видео: —";
  if (frozenV != null && currentV != null) {
    if (frozenV === currentV) {
      videoPart = `видео в теме: ${currentV} (без изменения числа в snapshot)`;
    } else {
      videoPart = `видео: ${frozenV} → ${currentV}`;
    }
  } else if (currentV != null) {
    videoPart = `видео сейчас: ${currentV}`;
  }

  let channelPart = "";
  if (frozenC != null || currentC != null) {
    channelPart = ` · каналы: ${frozenC ?? "—"} → ${currentC ?? "—"}`;
  }

  if (row.family_present === false) {
    return `${videoPart}${channelPart} · нет в bounded snapshot`;
  }
  if (row.family_present === true && frozenV != null && currentV != null && frozenV === currentV) {
    return `${videoPart}${channelPart} · состав snapshot может меняться без роста счётчика`;
  }
  return `${videoPart}${channelPart}`;
}
