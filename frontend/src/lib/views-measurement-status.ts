export type ViewsMeasurementStatus =
  | "from_winner_snapshot"
  | "from_snapshot"
  | "zero_in_winner_snapshot"
  | "zero_in_snapshot"
  | "unknown_in_winner_snapshot"
  | "unknown_in_snapshot"
  | "missing_snapshot";

export function viewsMeasurementLabel(status: ViewsMeasurementStatus | string): string {
  switch (status) {
    case "from_winner_snapshot":
      return "Просмотры из снимка Winners";
    case "from_snapshot":
      return "Просмотры из последнего снимка";
    case "zero_in_winner_snapshot":
      return "0 просмотров в снимке Winners (не провал темы)";
    case "zero_in_snapshot":
      return "0 просмотров в снимке (не провал темы)";
    case "unknown_in_winner_snapshot":
      return "Просмотры не указаны в снимке Winners";
    case "unknown_in_snapshot":
      return "Просмотры не указаны в снимке";
    case "missing_snapshot":
      return "Нет снимка — метрики не измерялись";
    default:
      return "Статус измерения неизвестен";
  }
}

export function formatViewsWithMeasurementStatus(
  formattedViews: string | null,
  status: ViewsMeasurementStatus | string,
): string {
  if (formattedViews) {
    return formattedViews;
  }
  if (
    status === "zero_in_snapshot" ||
    status === "zero_in_winner_snapshot"
  ) {
    return "0";
  }
  return "—";
}
