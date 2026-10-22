/* Browser-only API fixtures. Never imported by the application. */
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const base = process.env.RADAR_PREVIEW_URL || "http://127.0.0.1:3100";
const out = path.resolve(
  process.env.RADAR_SCREENSHOT_DIR || "../docs/frontend-redesign",
);
fs.mkdirSync(out, { recursive: true });
const now = new Date().toISOString();
const items = [
  [
    "zKt5IyhaToM",
    "Как устроен крошечный мир: строим миниатюрный дом с работающим освещением",
    "Мастерская миниатюр",
    42000,
    1750,
    827,
  ],
  [
    "zqHseu5J1qE",
    "Building a miniature workshop from everyday materials",
    "DIY Crasher",
    33000,
    1375,
    73500,
  ],
  [
    "u7Gyz1Mt_sM",
    "Почему привычные вещи кажутся нам необычными — история одного эксперимента",
    "Истории в деталях",
    24000,
    1000,
    530,
  ],
  [
    "bad-thumbnail",
    "Очень длинное название видео для проверки читабельности на узком экране: что произойдёт, если собрать целый город из картона и маленьких ламп",
    "Маленькие проекты",
    18000,
    750,
    2100,
  ],
].map(([id, title, channel, views, vph, subs], i) => ({
  video_id: id,
  title,
  channel_id: `channel-${i}`,
  channel_title: channel,
  youtube_url: `https://www.youtube.com/watch?v=${id}`,
  published_at: new Date(Date.now() - 86400000).toISOString(),
  age_hours: 24,
  views,
  vph,
  subscribers: subs,
  breakout_rank: i + 1,
  breakout_eligible: true,
  channel_relative_signal: null,
  acceleration_state: i === 0 ? "accelerating" : "stable",
  delayed_outcome_state: "pending",
  delayed_outcome_growth: null,
  reason_codes: [],
  human_reasons: [],
  keyword_ids: [1],
}));
const family = {
  family_key: "family:test:miniature",
  label: "Миниатюрные миры своими руками",
  family_kind: "title_phrase",
  member_pattern_keys: ["phrase:test"],
  member_labels: ["miniature workshop"],
  video_count: 4,
  channel_count: 4,
  keyword_count: 1,
  breakout_eligible_count: 4,
  videos_last_24h: 4,
  videos_previous_24h: 2,
  videos_previous_48_24h: 1,
  grouping_reasons: ["shared_phrase"],
  quality_flags: [],
  support_sources: ["title_phrase"],
  first_seen_at: now,
  latest_seen_at: now,
  participating_video_ids: items.map((x) => x.video_id),
  participating_channel_ids: items.map((x) => x.channel_id),
  participating_keyword_ids: [1],
};
const topic = {
  ...family,
  family_key: "family:test:topic",
  label: "DIY и миниатюры",
  family_kind: "keyword_provenance",
  quality_flags: ["keyword_only"],
};
const meta = {
  data_source: "snapshot",
  run_id: "browser_fixture",
  computed_at: now,
  limit: 50,
  offset: 0,
  total: 4,
};
const summary = {
  run_id: meta.run_id,
  computed_at: now,
  timezone_name: "UTC",
  window_hours: 24,
  window_start: now,
  window_end: now,
  source: "snapshot",
  candidate_video_count: 1240,
  winner_count: 4,
  pattern_count: 2,
  channel_momentum_count: 0,
  video_limit: 50,
  pattern_limit: 20,
  channel_limit: 20,
  notes: {},
};
let saved = false,
  mode = "ready";
let detail = {
  id: 1,
  family_key: family.family_key,
  status: "WATCHING",
  notes: "",
  tags: [],
  created_at: now,
  updated_at: now,
  archived_at: null,
  frozen_snapshot: {
    family,
    breakout_video_evidence: items,
    attention_run_id: meta.run_id,
  },
  live_observation: {
    id: 1,
    attention_run_id: meta.run_id,
    captured_at: now,
    payload: {
      counts: {
        video_count: 4,
        channel_count: 4,
        keyword_count: 1,
        breakout_eligible_count: 4,
      },
    },
  },
  count_deltas: null,
  latest_feedback: null,
};
const validation = {
  period: { start: null, end: null },
  topics_saved_in_period: 0,
  current_status_counts: {},
  status_transition_events: {},
  latest_finding_rating_distribution: {},
  topics_with_latest_feedback: 0,
  topics_with_own_test_video_url: 0,
  topics_with_known_own_test_outcome: 0,
  latest_observation_presence: {},
  topics_with_comparable_count_deltas: 0,
  frozen_support_source_breakdown: {},
  frozen_family_kind_breakdown: {},
  interpretation_notes: ["Отсутствие темы в подборке не означает провал."],
};
(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {}),
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1050 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("**/api/**", async (route) => {
    const u = new URL(route.request().url()),
      p = u.pathname;
    const respond = (data, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(data),
      });
    if (mode === "error")
      return respond({ detail: "Test API unavailable" }, 503);
    if (p === "/api/attention/summary")
      return respond({
        data_source: mode === "empty" ? "unavailable" : "snapshot",
        summary: mode === "empty" ? null : summary,
      });
    if (p === "/api/attention/videos") return respond({ ...meta, items });
    if (p === "/api/attention/channels") return respond({ ...meta, items: [] });
    if (p === "/api/attention/pattern-families")
      return respond({ ...meta, items: [family, topic] });
    if (p.startsWith("/api/attention/pattern-families/"))
      return respond({
        ...meta,
        family,
        videos: items.map((x) => ({ ...x, in_winner_snapshot: true })),
        related_keywords: [],
        channels: [],
        member_patterns: [],
      });
    if (p === "/api/saved-topics") {
      if (route.request().method() === "POST") {
        saved = true;
        return respond({ item: detail, created: true, idempotent: false });
      }
      return respond({
        items: saved
          ? [
              {
                ...detail,
                label: family.label,
                latest_observation_at: now,
                present_in_latest_snapshot: true,
              },
            ]
          : [],
        total: saved ? 1 : 0,
      });
    }
    if (p.endsWith("/timeline"))
      return respond({ items: [], total: 0, offset: 0, limit: 50 });
    if (p.endsWith("/archive")) {
      detail.archived_at = now;
      return respond(detail);
    }
    if (p.endsWith("/restore")) {
      detail.archived_at = null;
      return respond(detail);
    }
    if (p.endsWith("/feedback")) {
      detail.latest_feedback = {
        id: 1,
        recorded_at: now,
        ...route.request().postDataJSON(),
      };
      return respond(detail.latest_feedback);
    }
    if (p === "/api/saved-topics/1") {
      if (route.request().method() === "PATCH")
        detail = { ...detail, ...route.request().postDataJSON() };
      return respond(detail);
    }
    if (p === "/api/validation/report") return respond(validation);
    throw new Error(`Unexpected endpoint ${p}`);
  });
  await page.route("**/*bad-thumbnail*", (route) => route.abort());
  await page.goto(base + "/opportunities");
  await page.getByTestId("winner-row").first().waitFor();
  await page.screenshot({
    path: path.join(out, "opportunities-desktop.png"),
    fullPage: true,
  });
  await page.getByLabel("Поиск по названию или каналу").fill("ничегонет");
  await page.getByText("Видео не найдены", { exact: true }).waitFor();
  await page.getByLabel("Поиск по названию или каналу").fill("");
  await page.getByLabel("Сортировка видео").selectOption("views");
  await page.getByRole("button", { name: /Похожие находки/ }).click();
  await page.getByRole("heading", { name: "Подборки по теме" }).waitFor();
  await page.screenshot({
    path: path.join(out, "collections-desktop.png"),
    fullPage: true,
  });
  const save = page.getByTestId("save-pattern").first();
  await save.click();
  await page.getByTestId("save-pattern-saved").waitFor();
  await page.getByTestId("save-pattern-saved").click();
  await page.getByRole("heading", { name: "При сохранении" }).waitFor();
  await page.screenshot({
    path: path.join(out, "saved-topic-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "В архив", exact: true }).click();
  await page.getByRole("button", { name: "Восстановить", exact: true }).click();
  await page.goto(base + "/validation");
  await page.getByText("Здесь появятся результаты вашей разведки").waitFor();
  await page.screenshot({
    path: path.join(out, "results-empty.png"),
    fullPage: true,
  });
  await page.goto(base + "/opportunities");
  await page.getByTestId("winner-row").first().waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    "Mobile horizontal overflow",
  );
  await page.screenshot({
    path: path.join(out, "opportunities-mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Открыть меню" }).click();
  await page
    .getByRole("link", { name: "Сохранённые темы", exact: true })
    .waitFor({ state: "visible" });
  await page.keyboard.press("Escape");
  mode = "empty";
  await page.reload();
  await page.getByText("Подборка ещё не готова.").waitFor();
  mode = "error";
  await page.reload();
  await page.getByRole("button", { name: "Повторить", exact: true }).waitFor();
  mode = "ready";
  await page.getByRole("button", { name: "Повторить", exact: true }).click();
  await page.getByTestId("winner-row").first().waitFor();
  assert.equal(errors.length, 0, errors.join("\n"));
  fs.writeFileSync(
    path.join(out, "browser-check.json"),
    JSON.stringify(
      {
        source: "isolated browser API fixtures; no working database",
        checks: [
          "search",
          "sort",
          "sections",
          "topic classification",
          "save and open topic",
          "archive and restore",
          "validation empty",
          "mobile overflow",
          "menu Escape",
          "unavailable",
          "API error retry",
        ],
        pageErrors: errors,
      },
      null,
      2,
    ),
  );
  await browser.close();
  console.log("Browser smoke passed");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
