import axios from "axios";

import {
  mapCompetitorPreviewError,
  type CompetitorPreviewUserError,
} from "@/lib/competitor-multi-display";

export function competitorPreviewErrorFromUnknown(err: unknown): CompetitorPreviewUserError {
  if (axios.isAxiosError(err)) {
    const status = err.response?.status;
    let detail = err.message;
    const data = err.response?.data;
    if (typeof data?.detail === "string") {
      detail = data.detail;
    } else if (Array.isArray(data?.detail)) {
      detail = data.detail.map((d: { msg?: string }) => d.msg ?? "").join("; ");
    }
    return mapCompetitorPreviewError(detail, status);
  }
  if (err instanceof Error) {
    return mapCompetitorPreviewError(err.message);
  }
  return mapCompetitorPreviewError("Неизвестная ошибка");
}
