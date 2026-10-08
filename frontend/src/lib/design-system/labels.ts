/** Russian labels + short tooltips for operator UI (Stage 1.21B). */

export type ActivityState = "active_recently" | "stale_activity" | "error" | "unknown";
export type MonitoringWorkerState = "running" | "stale" | "stopped" | "unknown";
export type LifecycleStatus = "probation" | "active" | "weak" | "archived" | string;
export type EvidenceStatus = "insufficient" | "early" | "established" | string;
export type CheckpointStatus = "due" | "overdue" | "pending" | "active" | "stopped" | string;
export type CycleStatus = "ok" | "partial" | "failed" | "dry_run" | string;

export function systemActivityLabel(state: ActivityState | string | null | undefined): string {
  switch (state) {
    case "active_recently":
      return "Недавняя активность";
    case "stale_activity":
      return "Давно не было циклов";
    case "error":
      return "Ошибка";
    default:
      return "Статус неизвестен";
  }
}

export function monitoringWorkerLabel(state: MonitoringWorkerState | string | null | undefined): string {
  switch (state) {
    case "running":
      return "Воркер активен";
    case "stale":
      return "Состояние устарело";
    case "stopped":
      return "Воркер остановлен";
    default:
      return "Статус недоступен";
  }
}

export function lifecycleLabel(status: LifecycleStatus | null | undefined): string {
  if (!status) {
    return "—";
  }
  switch (status) {
    case "probation":
      return "Пробный";
    case "active":
      return "В работе";
    case "weak":
      return "Слабый сигнал";
    case "archived":
      return "Архив";
    default:
      return status;
  }
}

export function evidenceStatusLabel(status: EvidenceStatus | null | undefined): string {
  if (!status) {
    return "—";
  }
  switch (status) {
    case "insufficient":
      return "Мало данных";
    case "early":
      return "Ранняя стадия";
    case "established":
      return "Есть исходы 72 ч";
    default:
      return status;
  }
}

export function checkpointStatusLabel(status: CheckpointStatus | null | undefined): string {
  if (!status) {
    return "—";
  }
  switch (status) {
    case "due":
      return "Пора снять снимок";
    case "overdue":
      return "Просрочено";
    case "pending":
      return "Ожидает checkpoint";
    case "active":
      return "На контроле";
    case "stopped":
      return "Снято с мониторинга";
    case "completed":
      return "Снимок снят";
    case "fulfilled_late":
      return "Поздний захват (без окна)";
    case "expired":
      return "Окно истекло";
    default:
      return status;
  }
}

export function cycleStatusLabel(status: CycleStatus | null | undefined): string {
  if (!status) {
    return "—";
  }
  switch (status) {
    case "ok":
      return "Успешно";
    case "partial":
      return "Частично";
    case "failed":
      return "Сбой";
    case "dry_run":
      return "Пробный прогон";
    default:
      return status;
  }
}

export const METRIC_TOOLTIPS = {
  vph: "Просмотров в час (VPH) — скорость набора просмотров по последнему снимку или на момент находки.",
  dueKeyword: "Ключ достиг запланированного времени сканирования (next_scan_at).",
  dueCheckpoint: "Checkpoint видео попал в окно для снимка метрик.",
  overdue: "Checkpoint просрочен относительно планировщика мониторинга.",
  breakout: "Всплеск — попадание в верхний decile глобального пула по VPH (контекст сравнения, не оценка качества).",
  outcome72h:
    "Исход 72 ч — есть снимок просмотров в пределах допуска от discovery+72 часов.",
  attribution:
    "Атрибуция — какому ключу засчитывается video_id (все попадания или первый discovery).",
  evidence:
    "Надёжность данных: объём сканов, атрибуций, eligible для всплеска и измеренных исходов 72 ч.",
} as const;
