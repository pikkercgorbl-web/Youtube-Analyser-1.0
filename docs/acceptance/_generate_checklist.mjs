/**
 * One-off generator for v1_checklist.md — run: node docs/acceptance/_generate_checklist.mjs
 * Not part of application runtime.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dir = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(__dir, "v1_checklist.md");

function item(id, route, executor, cond, steps, expect, comment = "—") {
  return `#### ${id}

| Поле | Значение |
|------|----------|
| **Маршрут** | ${route} |
| **Исполнитель** | ${executor} |
| **Условия** | ${cond} |
| **Шаги** | ${steps} |
| **Ожидаемый результат** | ${expect} |
| **Результат** | НЕ ПРОВЕРЕН |
| **Фактическое поведение** | — |
| **Доказательство** | — |
| **Польза** | НЕ ОЦЕНЕНО |
| **Комментарий** | ${comment} |

`;
}

const ids = [];
let body = "";
function add(...args) {
  body += item(...args);
  ids.push(args[0]);
}

const header = `# Приёмка NicheScope v1 — чек-лист

## Метаданные прохождения (заполнить)

| Поле | Значение |
|------|----------|
| Дата начала | |
| Дата обновления | |
| Git commit | \`git rev-parse HEAD\` |
| Среда | Frontend; Backend; PostgreSQL |
| Роли | **Пользователь** — UI, польза; **Cursor** — TECH-*, API idempotent (COMMON-01/03/04) |

## Подготовка

- Этапы **A и B** допускают сохранения и редактирование notes/tags/status, archive/restore.
- Тестовые записи: notes с префиксом \`ACCEPTANCE_TEST\`; зафиксируйте ID в таблице. Не перезаписывайте важные пользовательские заметки.
- **ЗАБЛОКИРОВАН** — если нет данных/доступа; **НЕ ПРОШЁЛ** — только после выполнения шагов.
- Workers **выключены** на A/B/D/E.

| Сущность | saved id | video_id / family_key |
|----------|----------|------------------------|
| Manual video | | |
| OPP video | | |
| Family | | |

## Первая сессия

**NAV-01 → SRCH-02 → SRCH-15 → SAV-01 → SAV-V-01** (навигация, поиск, сохранение, список, карточка).

## Общие паттерны (COMMON)

`;

// COMMON + TECH
add(
  "COMMON-01",
  "(API)",
  "Cursor",
  "PostgreSQL; video_id не сохранён",
  "Дважды POST /api/manual-search/save-video с одним video_id",
  "Второй ответ: idempotent=true, created=false; одна активная saved row на video_id",
);
add(
  "COMMON-02",
  "(UI SaveVideoButton)",
  "Пользователь",
  "Кнопка «Сохранить» видна",
  "Два быстрых клика «Сохранить»",
  "Не более одного POST; затем ссылка «Сохранено» (data-testid save-video-saved)",
);
add(
  "COMMON-03",
  "(API)",
  "Cursor",
  "video_id в corpus",
  "Дважды POST /api/saved-videos",
  "idempotent=true; одна запись",
);
add(
  "COMMON-04",
  "(API)",
  "Cursor",
  "valid family_key",
  "Дважды POST /api/saved-families",
  "idempotent=true; одна запись",
);
add(
  "COMMON-05",
  "/saved/videos/{id}",
  "Пользователь",
  "Открыт SAV-V",
  "F5",
  "Frozen block unchanged; live may differ",
);
add(
  "COMMON-06",
  "/saved/videos/{id}",
  "Пользователь",
  "Есть live_observation",
  "Прочитать Monitoring в «Сейчас»",
  "«снимок доступен» или «снимок недоступен» — только про snapshot, не eligibility",
);

body += `\n## Технические проверки manual save (TECH)\n\n`;
add(
  "TECH-01",
  "PostgreSQL",
  "Cursor",
  "Новый video_id (insert Video через manual save)",
  "SELECT automatic_monitoring_withheld FROM videos WHERE id=?",
  "true",
);
add(
  "TECH-02",
  "PostgreSQL",
  "Cursor",
  "Тот же новый video_id",
  "Проверить отсутствие discovery hit для video_id (read-only SQL по schema)",
  "0 hits на момент save (read-only SQL)",
);
add(
  "TECH-03",
  "PostgreSQL",
  "Cursor",
  "Corpus video: withheld=false, есть snapshots",
  "Save через manual-search",
  "automatic_monitoring_withheld остаётся false",
);
add(
  "TECH-04",
  "PostgreSQL",
  "Cursor",
  "Video уже в monitoring queue",
  "Save existing corpus video",
  "Video не исключается из monitoring source (withheld false)",
);

body += `\n## Этап A — UI (workers выключены)\n\n### NAV\n\n`;
const nav = [
  ["NAV-01", "/", "Desktop ≥1280px", "Открыть /", "Sidebar: Разведка×4, Поиск×4, Сбор×2"],
  ["NAV-02", "/keywords", "", "Перейти /keywords", "«Поисковые запросы» active"],
  ["NAV-03", "/", "390px", "Меню → Возможности → Esc", "URL /opportunities; menu closed"],
  ["NAV-04", "/saved/videos/{id}", "Есть id", "Open link", "«Сохранённое» active"],
  ["NAV-05", "/opportunities/videos/{id}", "Snapshot есть", "Open", "«Возможности» active"],
  ["NAV-06", "/mass-analysis/channel?...", "", "Open", "«Анализ конкурентов» active"],
  ["NAV-07", "/monitoring/videos/{id}", "", "Open", "«Наблюдение за видео» active"],
  ["NAV-08", "/saved", "", "F5", "Same URL, list loads"],
];
nav.forEach(([id, r, c, s, e]) => add(id, r, "Пользователь", c, s, e));

body += `\n### SRCH\n\n`;
const srch = [
  ["SRCH-01", "/", "", "Open /", "«Введите запрос и нажмите «Найти»»"],
  ["SRCH-02", "/", "Backend+YT", "Query + «Найти»", "Cards; POST /api/search 2xx"],
  ["SRCH-03", "/", "", "Type 3+ chars wait", "Suggestions dropdown or empty"],
  ["SRCH-04", "/", "Results loaded", "«Фильтры» apply", "Filter chips visible"],
  ["SRCH-05", "/", "Multiple chips", "Remove one chip", "List matches remaining filters only"],
  ["SRCH-06", "/", "Chips present", "«Сбросить всё»", "No chips; full raw list locally"],
  ["SRCH-07", "/", "Filters exclude all", "Search", "«Нет видео, подходящих под выбранные фильтры…»"],
  ["SRCH-08", "/", "", "Obscure query", "«Ничего не найдено.»"],
  ["SRCH-09", "/", "Enrich runs", "Wait after search", "Subscriber skeleton clears"],
  ["SRCH-10", "/", "in_corpus", "", "Badge «Уже в базе»"],
  ["SRCH-11", "/", "ctx.saved_video_id", "", "Link «Сохранено»"],
  ["SRCH-12", "/", "snapshot_count>0", "", "«История snapshots» → MON-V"],
  ["SRCH-13", "/", "channel_id", "«Анализ канала»", "CHAN URL with focus"],
  ["SRCH-14", "/", "", "Click title", "youtube.com/watch opens"],
  [
    "SRCH-15",
    "/",
    "Unsaved video",
    "«Сохранить»",
    "COMMON-01, COMMON-02; link «Сохранено»",
  ],
  ["SRCH-16", "/", "from_saved", "From SAV-V link", "Search with context"],
];
srch.forEach(([id, r, c, s, e]) => add(id, r, "Пользователь", c, s, e));

body += `\n### COMP\n\n`;
const comp = [
  ["COMP-01", "/mass-analysis", "", "Single channel URL + «Анализ канала»", "Navigate CHAN"],
  ["COMP-02", "/mass-analysis", "", "2 URLs in textarea", "«Уникальных строк:» ≥2"],
  ["COMP-03", "/mass-analysis", "", "1 URL only", "«Загрузить обзор» disabled or invalid"],
  ["COMP-04", "/mass-analysis", "", "6 URLs", "Cannot load (>5)"],
  ["COMP-05", "/mass-analysis", "", "«Загрузить обзор» 2 valid", "Heading «Каналы»; cards"],
  ["COMP-06", "/mass-analysis", "", "1 valid + 1 invalid URL", "Success channel remains; «Не загружен»"],
  ["COMP-07", "/mass-analysis", "After COMP-06", "«Повторить» on failed", "Retry fetch failed ref only"],
  ["COMP-08", "/mass-analysis", "Feed loaded", "Channel select filter", "Feed subset one channel"],
  ["COMP-09", "/mass-analysis", "", "«Новые»", "Order by date changes"],
  ["COMP-10", "/mass-analysis", "", "«Больше просмотров»", "Order by views changes"],
  ["COMP-11", "/mass-analysis", "", "«Анализ канала» on card", "CHAN with focus_video_id"],
  ["COMP-12", "/mass-analysis", "", "«Сохранить» on card", "COMMON-01/02 manual"],
  ["COMP-13", "/mass-analysis", "", "Thumbnail link", "YouTube opens"],
  ["COMP-14", "/mass-analysis", "", "Second «Загрузить обзор»", "Previous requests aborted; new generation"],
];
comp.forEach(([id, r, c, s, e]) => add(id, r, "Пользователь", c, s, e));

body += `\n### CHAN\n\n`;
const chan = [
  ["CHAN-01", "/mass-analysis/channel", "Valid channel_id in URL", "Open", "Channel header card"],
  ["CHAN-02", "/mass-analysis/channel", "", "During shelf load", "«Загружаем публикации канала…» then clears"],
  ["CHAN-03", "/mass-analysis/channel", "Invalid channel", "Open", "«Канал не загружен» + message"],
  ["CHAN-04", "/mass-analysis/channel", "Loaded", "", "Subscriber count line if present"],
  ["CHAN-05", "/mass-analysis/channel", "focus_video_id set", "", "ChannelSingleFocusCompact visible"],
  ["CHAN-06", "/mass-analysis/channel", "", "«Сравнить» on card", "focus_video_id updates; compare block updates"],
  ["CHAN-07", "/mass-analysis/channel", "", "Sort «Новые»", "Grid order changes"],
  ["CHAN-08", "/mass-analysis/channel", "", "Sort «Больше просмотров»", "Grid order changes"],
  ["CHAN-09", "/mass-analysis/channel", "", "Wait enrich", "«Уточняем метаданные…» then grid ready"],
  ["CHAN-10", "/mass-analysis/channel", "enrichedReady empty", "", "«Нет подтверждённых обычных видео…»"],
  [
    "CHAN-11",
    "/mass-analysis/channel",
    "hasMoreShelf",
    "«Загрузить ещё» success",
    "feedLoadedCount increases; button ends loading state (not «Загружаем…» stuck)",
  ],
  [
    "CHAN-12",
    "/mass-analysis/channel",
    "hasMoreShelf + force error",
    "«Загрузить ещё» when API fails",
    "Amber/error loadMoreError text; shelf count unchanged from last success",
  ],
  [
    "CHAN-13",
    "/mass-analysis/channel",
    "After CHAN-11",
    "Count video_id in grid",
    "No duplicate video_id rows in grid",
  ],
  [
    "CHAN-14",
    "/mass-analysis/channel",
    "focus set + load more",
    "«Загрузить ещё»",
    "focus_video_id unchanged; focus card still same video",
  ],
  ["CHAN-15", "/mass-analysis/channel", "", "Full load cycle", "shelfLoading false after success or error"],
  ["CHAN-16", "/mass-analysis/channel", "", "«Сохранить»", "COMMON-01/02"],
  ["CHAN-17", "/mass-analysis/channel", "No query", "Ref + «Открыть»", "URL updates; shelf loads"],
  ["CHAN-18", "/mass-analysis/channel", "", "«Канал на YouTube»", "External channel URL"],
];
chan.forEach(([id, r, c, s, e]) => add(id, r, "Пользователь", c, s, e));

// Continue OPP, etc. - add remaining sections in same file via append in script

function section(title, rows, executor = "Пользователь") {
  body += `\n### ${title}\n\n`;
  rows.forEach(([id, r, c, s, e]) => add(id, r, executor, c, s, e));
}

section("OPP", [
  ["OPP-01", "/opportunities", "No snapshot", "Open", "«Снимок Attention ещё не создан»; link /operations"],
  ["OPP-02", "/opportunities", "Empty snapshot", "Open", "Banner opp-empty-snapshot"],
  ["OPP-03", "/opportunities", "Data snapshot", "Open", "summary-cards visible counts"],
  ["OPP-04", "/opportunities", "", "Click videos/channels/families cards", "Section content switches"],
  ["OPP-05", "/opportunities", "Stale computed_at", "", "Amber freshness text"],
  ["OPP-06", "/opportunities", "", "Open «О данных»", "run_id and computed_at shown"],
  ["OPP-07", "/opportunities", "Winners exist", "Search input «Поиск по названию или каналу»", "rows.length matches filter"],
  ["OPP-08", "/opportunities", "", "Sort «По рейтингу Radar» (default)", "breakout order"],
  ["OPP-09", "/opportunities", "", "Sort «Просмотры в час»", "Order changes"],
  ["OPP-10", "/opportunities", "", "Sort «Просмотры»", "Order changes"],
  ["OPP-11", "/opportunities", "", "Sort «Возраст»", "Order changes"],
  ["OPP-12", "/opportunities", "Filter no match", "", "«Видео не найдены»"],
  ["OPP-13", "/opportunities", ">12 winners", "«Показать ещё N видео»", "visibleCount increases by 12"],
  ["OPP-14", "/opportunities", "", "«Детали видео»", "/opportunities/videos/{id}"],
  ["OPP-15", "/opportunities", "", "«Динамика видео»", "/monitoring/videos/{id}"],
  ["OPP-16", "/opportunities", "", "SaveVideoButton «Сохранить»", "COMMON-03 + COMMON-02"],
  ["OPP-17", "/opportunities", "Related family", "«Сохранить тему»", "COMMON-04"],
  ["OPP-18", "/opportunities", "", "Family name link", "/opportunities/families/{key}"],
  ["OPP-19", "/opportunities", "", "Tab «Растущие каналы»", "RisingChannelsSection visible"],
  ["OPP-20", "/opportunities", "", "«Изучить подборку →»", "Family detail"],
  ["OPP-21", "/opportunities", "", "URL #winner={id}", "Videos tab focuses row"],
]);

section("OPP-V", [
  ["OPP-V-01", "/opportunities/videos/{id}", "Valid id", "Open", "Title + thumb load"],
  ["OPP-V-02", "/opportunities/videos/{id}", "Invalid id", "Open", "Error or unavailable state"],
  ["OPP-V-03", "/opportunities/videos/{id}", "", "«Почему видео в Winners»", "Section text present"],
  ["OPP-V-04", "/opportunities/videos/{id}", "", "Save video", "COMMON-03"],
  ["OPP-V-05", "/opportunities/videos/{id}", "", "«Назад к находкам»", "/opportunities"],
  ["OPP-V-06", "/opportunities/videos/{id}", "", "Discovery keywords block", "Keywords or empty copy"],
  ["OPP-V-07", "/opportunities/videos/{id}", "No baseline", "", "baseline-unavailable message"],
  ["OPP-V-08", "/opportunities/videos/{id}", "", "YouTube link", "Opens watch"],
]);

section("OPP-F", [
  ["OPP-F-01", "/opportunities/families/{key}", "", "Open from card", "Family title loads"],
  ["OPP-F-02", "/opportunities/families/{key}", "", "SaveFamilyButton", "COMMON-04"],
  ["OPP-F-03", "/opportunities/families/{key}", "", "Member video links", "OPP-V or YouTube"],
  ["OPP-F-04", "/opportunities/families/{key}", "", "Back link", "/opportunities"],
]);

section("OPP-P", [
  ["OPP-P-01", "/opportunities/patterns/{key}", "", "Open", "Pattern label"],
  ["OPP-P-02", "/opportunities/patterns/{key}", "", "Back", "/opportunities"],
]);

section("DI", [
  ["DI-01", "/daily-intelligence", "No dates", "Open", "«Исторических отчётов пока нет»"],
  ["DI-02", "/daily-intelligence", "Dates exist", "Pick date", "Report sections load"],
  ["DI-03", "/daily-intelligence", "", "?date= in URL", "Date synced"],
  ["DI-04", "/daily-intelligence", "", "Winners pagination «Вперёд»", "Offset changes"],
  ["DI-05", "/daily-intelligence", "", "Families pagination", "Offset changes"],
  ["DI-06", "/daily-intelligence", "", "Runs pagination", "Offset changes"],
  ["DI-07", "/daily-intelligence", "Empty winners day", "", "«Нет winners»"],
  ["DI-08", "/daily-intelligence", "", "Outcome coverage block", "Section renders or error with retry"],
]);

section("DI-V", [
  ["DI-V-01", "/daily-intelligence/{date}/winners/{videoId}", "", "Open from DI", "Winner detail"],
  ["DI-V-02", "/daily-intelligence/{date}/winners/{videoId}", "", "Back navigation", "Returns to DI date"],
]);

section("DI-F", [
  ["DI-F-01", "/daily-intelligence/{date}/families/{familyKey}", "", "Open", "Family detail"],
]);

section("SAV", [
  ["SAV-01", "/saved", "", "Open", "Tabs Видео/Темы"],
  ["SAV-02", "/saved", "Empty", "", "«Нет сохранённых видео.»"],
  ["SAV-03", "/saved", "", "Switch «Темы» tab", "Families list"],
  ["SAV-04", "/saved", "Has video", "Click list item", "SAV-V opens"],
  ["SAV-05", "/saved", "", "Feedback panel", "Loads without error"],
  ["SAV-06", "/saved", "API error", "Retry on ErrorState", "List loads — see D-SAV-01"],
]);

section("SAV-V", [
  ["SAV-V-01", "/saved/videos/{id}", "", "Open test video", "Title + frozen block"],
  ["SAV-V-02", "/saved/videos/{id}", "Manual new save", "", "TECH-01/02; UI copy no auto monitoring"],
  ["SAV-V-03", "/saved/videos/{id}", "Corpus monitored", "", "TECH-03/4; monitoring snapshots copy"],
  ["SAV-V-04", "/saved/videos/{id}", "", "Change status + «Сохранить»", "PATCH 2xx; message «Сохранено»"],
  ["SAV-V-05", "/saved/videos/{id}", "", "Edit notes/tags save", "PATCH persists after F5"],
  ["SAV-V-06", "/saved/videos/{id}", "", "«Убрать из сохранённых»", "archived_at set; banner"],
  ["SAV-V-07", "/saved/videos/{id}", "Archived", "«Восстановить»", "Active in list"],
  ["SAV-V-08", "/saved/videos/{id}", "", "«Обновить статистику»", "POST refresh-metrics 2xx"],
  ["SAV-V-09", "/saved/videos/{id}", "", "History «Загрузить ещё» if present", "More observations"],
  ["SAV-V-10", "/saved/videos/{id}", "", "Analyst feedback submit", "POST feedback 2xx"],
  ["SAV-V-11", "/saved/videos/{id}", "", "Link to manual search", "from_saved works SRCH-16"],
  ["SAV-V-12", "/saved/videos/{id}", "", "COMMON-05 frozen/live", ""],
  ["SAV-V-13", "/saved/videos/{id}", "", "COMMON-06 monitoring label", ""],
]);

section("SAV-F", [
  ["SAV-F-01", "/saved/families/{id}", "", "Open", "Label loads"],
  ["SAV-F-02", "/saved/families/{id}", "", "Metadata save", "PATCH 2xx"],
  ["SAV-F-03", "/saved/families/{id}", "", "Archive / restore", "Same as SAV-V-06/07 pattern"],
  ["SAV-F-04", "/saved/families/{id}", "", "Feedback panel", "POST works"],
]);

section("VAL", [
  ["VAL-01", "/validation", "", "Open", "Report sections"],
  ["VAL-02", "/validation", "", "Set period dates + reload", "Filtered counts change or stay valid"],
  ["VAL-03", "/validation", "", "Portfolio link to saved", "Opens SAV-V or SAV-F"],
]);

section("KW", [
  ["KW-01", "/keywords", "Pool data", "Open", "Metrics + table OR empty"],
  ["KW-02", "/keywords", "target_keywords empty", "Open", "keyword-pool-empty; NOT error StateMessage"],
  ["KW-03", "/keywords", "", "«Обновить»", "Data refreshes"],
  ["KW-04", "/keywords", "", "Filter search text", "Rows subset"],
  ["KW-05", "/keywords", "", "Lifecycle filter", "Rows subset"],
  ["KW-06", "/keywords", "", "Due filter «Пора сканировать»", "Rows subset"],
  ["KW-07", "/keywords", "", "Sort «По keyword»", "Order changes"],
  ["KW-08", "/keywords", "Filters no match", "", "«Нет ключей по фильтрам»"],
  ["KW-09", "/keywords", "", "Source filter select", "Rows subset"],
  ["KW-10", "/keywords", "", "Sort «По последнему скану»", "Order changes"],
]);

section("KWP", [
  ["KWP-01", "/keyword-performance", "", "Open", "Tables load"],
  ["KWP-02", "/keyword-performance", "", "Tab Breakout", "Breakout table"],
  ["KWP-03", "/keyword-performance", "", "Tab 72h исходы", "Outcomes table"],
  ["KWP-04", "/keyword-performance", "", "Attribution toggle", "Data refetch"],
  ["KWP-05", "/keyword-performance", "", "Limit 50/100/500", "Row count bound"],
  ["KWP-06", "/keyword-performance", "", "Search filter", "Subset"],
  ["KWP-07", "/keyword-performance", "", "Row → detail", "KWP-D opens"],
  ["KWP-08", "/keyword-performance", "Empty DB", "", "«Нет ключевых слов»"],
]);

section("KWP-D", [
  ["KWP-D-01", "/keyword-performance/{keywordId}", "", "Open", "Keyword header"],
  ["KWP-D-02", "/keyword-performance/{keywordId}", "", "Back arrow", "KWP list"],
]);

section("MON", [
  ["MON-01", "/monitoring", "", "Open", "Overview metrics"],
  ["MON-02", "/monitoring", "", "Tab «Очередь (по умолчанию)»", "Priority mode"],
  ["MON-03", "/monitoring", "", "Tab breakout mode", "Breakout empty title if none"],
  ["MON-04", "/monitoring", "", "Tier filter B", "Table subset"],
  ["MON-05", "/monitoring", "Priority mode", "Status filter", "Subset"],
  ["MON-06", "/monitoring", "", "Title search + «Применить»", "Filtered videos"],
  ["MON-07", "/monitoring", "", "Priority sort select", "Order changes"],
  ["MON-08", "/monitoring", "", "Open video row", "MON-V"],
  ["MON-09", "/monitoring", "", "Cycles disclosure", "Cycle rows visible"],
  ["MON-10", "/monitoring", "Partial cycle in DB", "", "execution_error_count vs missing columns visible"],
  ["MON-11", "/monitoring", "Pagination", "Next page if total>page", "Offset increases; rows change"],
]);

section("MON-V", [
  ["MON-V-01", "/monitoring/videos/{videoId}", "Valid", "Open", "Detail loads"],
  ["MON-V-02", "/monitoring/videos/{videoId}", "Invalid", "Open", "«Не удалось загрузить видео»"],
]);

section("OPS", [
  ["OPS-01", "/operations", "", "Open", "Discovery + Monitoring sections"],
  ["OPS-02", "/operations", "", "«Обновить» if present", "Overview refreshes"],
  ["OPS-03", "/operations", "No worker data", "", "«Данных пока нет» or zeros"],
  ["OPS-04", "/operations", "", "72h attribution toggle", "UI toggles; data block updates"],
  ["OPS-05", "/operations", "", "Discovery cycles table expand", "Cycle rows"],
  ["OPS-06", "/operations", "", "Monitoring cycles table", "Cycle rows"],
  ["OPS-07", "/operations", "", "Кнопка «Обновить»", "Overview refetch; RefreshingIndicator"],
  ["OPS-08", "/operations", "Errors in DB", "", "operations-errors-section text visible"],
]);

section("MOB", [
  ["MOB-01", "/opportunities", "390px", "Open winners", "Cards readable"],
  ["MOB-02", "/mass-analysis", "390px", "", "Textarea + load usable"],
  ["MOB-03", "/saved", "390px", "", "List scrolls"],
]);

section("LEG-LINK", [
  ["LEG-LINK-01", "/explosive-channels", "", "Direct URL", "Page loads; not in sidebar"],
  ["LEG-LINK-02", "/leaders", "", "Direct URL", "Page loads"],
  ["LEG-LINK-03", "/anomalies", "", "Direct URL", "Page loads"],
  ["LEG-LINK-04", "/keyword-research", "", "Direct URL", "Page loads"],
  ["LEG-LINK-05", "/keyword-analyze", "", "Direct URL", "Page loads"],
  ["LEG-LINK-06", "/saved-keywords", "", "Direct URL", "Page loads"],
  ["LEG-LINK-07", "/saved-topics", "", "Direct URL", "Page loads; OPP save → /saved/families not /saved-topics"],
]);

body += `\n## Этап B — Сквозные сценарии\n\n`;
const b = [
  ["B-01", "SRCH-15 → SAV-01 → SAV-V-04", "Notes saved"],
  ["B-02", "COMP-12 → SAV-01", "Video in list"],
  ["B-03", "OPP-15 → SAV-F-01", "Family in tab"],
  ["B-04", "OPP-12 → OPP-V-04 → SAV", "Winner saved"],
  ["B-05", "SAV-V-06 → SAV-01 → restore SAV-V-07", "Archive cycle"],
  ["B-06", "COMMON-01 after SRCH-15", "Idempotent"],
  ["B-07", "SRCH-13 → CHAN-16 → SAV", "Channel path save"],
  ["B-08", "SRCH-12 → MON-V-01", "Snapshots link"],
  ["B-09", "TECH-01 after SRCH-15 new video", "withheld true"],
  ["B-10", "TECH-03 after save corpus video", "withheld unchanged"],
];
b.forEach(([id, route, expect]) =>
  add(id, route, "Пользователь + Cursor", "Test entities recorded", "Execute linked IDs in order", expect),
);

body += `\n## Этап C — Фон (отдельный запуск; сейчас не выполнять)\n\n`;
const c = [
  [
    "BG-D-01",
    "Terminal",
    "Cursor",
    "PG up; preflight ok",
    ".\\scripts\\start-discovery.ps1 — default interval 300s batch 5",
    "OPS discovery last cycle time advances; Ctrl+C stops",
  ],
  [
    "BG-D-02",
    "Terminal",
    "Cursor",
    "",
    ".\\scripts\\start-discovery.ps1 -DryRun",
    "Plan printed; no worker",
  ],
  [
    "BG-M-01",
    "Terminal",
    "Cursor",
    "",
    ".\\scripts\\start-monitoring.ps1",
    "MON worker status; cycles in OPS/MON",
  ],
  [
    "BG-O-01",
    "Terminal",
    "Cursor",
    "Use explicit config (not silent default 3600/0)",
    ".\\scripts\\start-outcome.ps1 -MaxVideos 1000 -IntervalSeconds 900",
    "Log shows max_videos=1000 interval 900; OPS outcome block updates",
  ],
  [
    "BG-O-02",
    "Terminal",
    "Cursor",
    "",
    ".\\scripts\\start-outcome.ps1 -DryRun",
    "Command plan includes params",
  ],
  [
    "BG-A-01",
    "Terminal",
    "Cursor",
    "",
    ".\\scripts\\start-attention-loop.ps1 -IntervalSeconds 3600",
    "OPP computed_at fresh; DI dates may update via capture hook",
  ],
  [
    "BG-A-02",
    "Terminal",
    "Cursor",
    "",
    "python scripts/refresh_attention_engine.py --dry-run",
    "No DB write; exit 0",
  ],
  [
    "BG-KP-01",
    "Terminal",
    "Cursor",
    "",
    ".\\scripts\\start-keyword-performance-loop.ps1",
    "KWP computed_at updates",
  ],
  [
    "BG-DI-01",
    "Docs",
    "Cursor",
    "After BG-A-01",
    "No separate capture worker; finalize: python scripts/finalize_daily_intelligence_reports.py",
    "DI archive dates lock/finalize per script",
  ],
  [
    "BG-LOCK-01",
    "Isolated PG test",
    "Cursor",
    "Two terminals",
    "Parallel refresh_attention_engine",
    "Second exit code 2",
  ],
  [
    "BG-OUT-READ-01",
    "KWP + OPS",
    "Пользователь",
    "After BG-O-01 running; DB has matured outcomes",
    "View existing outcome rows (no 72h wait)",
    "Outcomes tab shows valid/missing counts",
  ],
];
c.forEach(([id, r, ex, cond, steps, expect]) => add(id, r, ex, cond, steps, expect));

body += `\n## Этап D — Ошибки (изолированная среда; mock/intercept)\n\n`;
const d = [
  [
    "D-01",
    "/",
    "Cursor+Пользователь",
    "Test frontend; backend stopped",
    "SRCH-02",
    "Red alert search error; no infinite «Ищем видео…»",
  ],
  [
    "D-02",
    "/opportunities",
    "",
    "Backend stopped",
    "Open OPP",
    "ErrorState «Не удалось загрузить находки» + retry",
  ],
  [
    "D-03",
    "/keywords",
    "",
    "Backend stopped",
    "Open KW",
    "StateMessage error; rows null — not empty pool",
  ],
  [
    "D-04",
    "/",
    "",
    "Playwright route abort POST /api/search",
    "Search",
    "Same as D-01 user-visible error",
  ],
  [
    "D-05",
    "/mass-analysis",
    "",
    "Intercept competitors/channel 502 once",
    "Load overview",
    "Failed channel error; successful unchanged COMP-06",
  ],
  [
    "D-06",
    "/saved",
    "",
    "Backend stopped",
    "Open SAV",
    "ErrorState + onRetry",
  ],
  [
    "D-07",
    "/monitoring/videos/badid",
    "",
    "",
    "Open",
    "MON-V-02 error UI",
  ],
  [
    "D-08",
    "/saved/videos/{id}",
    "",
    "PATCH intercept 500",
    "Save notes",
    "saveError shown; notes not falsely «Сохранено»",
  ],
];
d.forEach(([id, r, ex, cond, steps, expect]) => add(id, r, ex, cond, steps, expect));

body += `\n## Этап E — Практическая польза (одна тема)\n\n`;
const e = [
  [
    "E-01",
    "Multi routes",
    "Пользователь",
    "Pick real niche topic",
    "SRCH/COMP/OPP find 2+ examples; save ≥1",
    "Recorded video_ids + why chosen (text)",
  ],
  [
    "E-02",
    "Reflect",
    "Пользователь",
    "",
    "Write 3+ sentences why examples fit niche",
    "Completed notes in comment field",
  ],
  [
    "E-03",
    "COMP/CHAN",
    "Пользователь",
    "",
    "Use competitor/channel analysis",
    "Can state one insight from CHAN compare",
  ],
  [
    "E-04",
    "Creative",
    "Пользователь",
    "",
    "Formulate one own video idea from evidence",
    "Idea text recorded",
  ],
  [
    "E-05",
    "Gaps",
    "Пользователь",
    "",
    "List missing data for go/no-go",
    "Specific gaps named",
  ],
  [
    "E-06",
    "Multi routes",
    "Пользователь",
    "После прохода A/B",
    "Перечислить экраны/кнопки, которые не помогли принять решение",
    "Допустим результат «работает, но не помогло»; зафиксировать в комментарии",
  ],
  [
    "E-07",
    "Итог темы",
    "Пользователь",
    "",
    "Оценить общую пользу сессии по теме",
    "Польза: ПОЛЕЗНО / НЕПОНЯТНО / НЕ НУЖНО / НЕ ОЦЕНЕНО",
  ],
];
e.forEach(([id, r, ex, cond, steps, expect]) => add(id, r, ex, cond, steps, expect));

const commonCount = ids.filter((x) => x.startsWith("COMMON")).length;
const techCount = ids.filter((x) => x.startsWith("TECH")).length;
const stageA = ids.filter((x) =>
  /^(NAV|SRCH|COMP|CHAN|OPP|DI|DI-V|DI-F|SAV|VAL|KW|KWP|MON|OPS|MOB|LEG-LINK)/.test(x) &&
  !/^SAV-V/.test(x) &&
  !/^SAV-F/.test(x) &&
  !/^MON-V/.test(x) &&
  !/^OPP-V|^OPP-F|^OPP-P/.test(x) &&
  (x.startsWith("SAV-") ? /^SAV-\d/.test(x) : true) &&
  (x.startsWith("MON-") ? /^MON-\d/.test(x) : true),
).length;
const stageB = ids.filter((x) => x.startsWith("B-")).length;
const stageC = ids.filter((x) => x.startsWith("BG-")).length;
const stageD = ids.filter((x) => x.startsWith("D-")).length;
const stageE = ids.filter((x) => x.startsWith("E-")).length;

body += `\n---\n\n## Итоговый подсчёт\n\n| Категория | Количество |\n|-----------|------------|\n| COMMON | ${commonCount} |\n| TECH | ${techCount} |\n| Этап A (UI) | ${stageA} |\n| Этап B | ${stageB} |\n| Этап C | ${stageC} |\n| Этап D | ${stageD} |\n| Этап E | ${stageE} |\n| **Всего ID** | **${ids.length}** |\n`;

function idsFor(prefix) {
  return ids.filter((x) => x.startsWith(prefix)).join(", ");
}
body += `\n## Таблица покрытия\n\n| Раздел | ID (полный список) |\n|--------|-------------------|\n`;
const groups = [
  ["COMMON/TECH", ["COMMON", "TECH"]],
  ["NAV", ["NAV-"]],
  ["SRCH", ["SRCH-"]],
  ["COMP", ["COMP-"]],
  ["CHAN", ["CHAN-"]],
  ["OPP hub", ["OPP-"]], // filtered below
  ["OPP-V", ["OPP-V-"]],
  ["OPP-F", ["OPP-F-"]],
  ["OPP-P", ["OPP-P-"]],
  ["DI", ["DI-"]],
  ["DI-V", ["DI-V-"]],
  ["DI-F", ["DI-F-"]],
  ["SAV", ["SAV-"]],
  ["SAV-V", ["SAV-V-"]],
  ["SAV-F", ["SAV-F-"]],
  ["VAL", ["VAL-"]],
  ["KW", ["KW-"]],
  ["KWP", ["KWP-"]],
  ["KWP-D", ["KWP-D-"]],
  ["MON", ["MON-"]],
  ["MON-V", ["MON-V-"]],
  ["OPS", ["OPS-"]],
  ["MOB", ["MOB-"]],
  ["LEG-LINK", ["LEG-LINK-"]],
  ["B", ["B-"]],
  ["BG", ["BG-"]],
  ["D", ["D-"]],
  ["E", ["E-"]],
];
for (const [name, prefixes] of groups) {
  const list = ids
    .filter((x) => {
      if (name === "SAV hub") return /^SAV-\d/.test(x);
      if (name === "MON") return /^MON-\d/.test(x);
      if (name === "OPP hub") return /^OPP-\d/.test(x);
      return prefixes.some((p) => x.startsWith(p));
    })
    .join(", ");
  body += `| ${name} | ${list} |\n`;
}

fs.writeFileSync(out, header + body);
console.log("Wrote", out, "IDs:", ids.length);
