"use client";

import { SectionPanel } from "@/components/design-system";
import { DELAYED_OUTCOME_LABELS, EVIDENCE_STATE_LABELS } from "@/lib/saved-research-labels";

type Props = {
  title?: string;
  validation: Record<string, unknown>;
  /** When true, show family-specific presence hints from validation payload. */
  kind?: "video" | "family";
};

export function SavedResearchValidationPanel({
  title = "Сравнение с наблюдениями",
  validation,
  kind = "video",
}: Props) {
  const state = String(validation.evidence_state ?? "");
  const stateLabel = EVIDENCE_STATE_LABELS[state] ?? state;

  return (
    <SectionPanel title={title} description="Не оценивает, была ли идея полезной — только наличие данных">
      <p className="text-sm font-medium">{stateLabel}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Это не вердикт аналитика. Оценку полезности задайте отдельно в блоке «Оценка аналитика».
      </p>
      {validation.view_delta != null ? (
        <p className="text-sm mt-3">
          Δ просмотров от сохранения:{" "}
          {Number(validation.view_delta) > 0 ? "+" : ""}
          {Number(validation.view_delta).toLocaleString("ru-RU")}
          {validation.view_delta_pct != null
            ? ` (${Number(validation.view_delta_pct) > 0 ? "+" : ""}${validation.view_delta_pct}%)`
            : ""}
        </p>
      ) : null}
      {kind === "family" && validation.family_presence_state ? (
        <p className="text-sm mt-2">
          В выборке Attention:{" "}
          {validation.family_presence_state === "in_bounded_snapshot"
            ? "тема в bounded snapshot"
            : validation.family_presence_state === "not_in_bounded_snapshot"
              ? "нет в текущей bounded snapshot"
              : "неизвестно"}
        </p>
      ) : null}
      {validation.delayed_72h_state ? (
        <p className="text-sm mt-2">
          72ч (Attention):{" "}
          {DELAYED_OUTCOME_LABELS[String(validation.delayed_72h_state)] ??
            String(validation.delayed_72h_state)}
        </p>
      ) : null}
      {Array.isArray(validation.unverified_hypotheses) &&
      validation.unverified_hypotheses.length > 0 ? (
        <ul className="mt-2 list-disc pl-5 text-xs text-muted-foreground">
          {(validation.unverified_hypotheses as string[]).map((h) => (
            <li key={h}>{h}</li>
          ))}
        </ul>
      ) : null}
    </SectionPanel>
  );
}
