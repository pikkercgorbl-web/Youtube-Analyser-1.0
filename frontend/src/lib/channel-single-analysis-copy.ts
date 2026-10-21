/**
 * User-facing copy for single-channel analysis (SRCH-08).
 * Wording aligned with channel_single_analysis_compare.py age-peer heuristic:
 * regular videos only; peer age in [0.75×, 1.25×] focus age; focus ≥48h; ≥5 peers for multiplier.
 */

export const CHANNEL_SINGLE_COMPARE_HINT =
  "Выберите ролик ниже — сравним его с другими обычными видео этого канала похожего возраста.";

export const CHANNEL_SINGLE_COMPARE_BUTTON_LABEL = "Сравнить этот ролик";

export const CHANNEL_SINGLE_COMPARE_SELECTED_LABEL = "Выбран для сравнения";

export const CHANNEL_SINGLE_COMPARE_METHOD_NOTE =
  "Обычные ролики (не Shorts и не трансляции): возраст peer от 75% до 125% от возраста выбранного; для коэффициента нужно не меньше 5 таких роликов, сам ролик — старше 48 ч.";
