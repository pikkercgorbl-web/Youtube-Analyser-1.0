/**
 * Единый календарный часовой пояс продукта (UI, фильтры по датам, VAL-05).
 *
 * Отдельного профиля timezone пользователя в приложении нет — используется этот default.
 * Override: NEXT_PUBLIC_APP_TIMEZONE (legacy alias: NEXT_PUBLIC_VALIDATION_PERIOD_TIMEZONE).
 */
export const APP_TIMEZONE =
  process.env.NEXT_PUBLIC_APP_TIMEZONE?.trim() ||
  process.env.NEXT_PUBLIC_VALIDATION_PERIOD_TIMEZONE?.trim() ||
  "Asia/Almaty";

/** @deprecated Используйте APP_TIMEZONE — оставлено для совместимости импортов VAL-05. */
export const VALIDATION_PERIOD_TIMEZONE = APP_TIMEZONE;
