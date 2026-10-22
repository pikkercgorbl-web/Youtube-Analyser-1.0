const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

const base = process.env.RADAR_ACCEPTANCE_URL || "http://127.0.0.1:3100";
const out = path.resolve(__dirname, "../../artifacts/fix_2b_acceptance_screenshots");
fs.mkdirSync(out, { recursive: true });

async function waitWinnerVisible(page, videoId, timeout = 60_000) {
  await page.waitForFunction(
    (id) => {
      const tab = document.querySelector('[data-testid="metric-winners"]')?.closest("button");
      if (tab?.getAttribute("aria-pressed") !== "true") return false;
      const row = document.getElementById(`winner-${id}`);
      return Boolean(row && !row.closest("[hidden]"));
    },
    videoId,
    { timeout },
  );
}

(async () => {
  const report = { base, checks: [], badResponses: [], screenshots: [] };
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on("response", (response) => {
    const url = response.url();
    if (url.includes("/_next/static/") && response.status() >= 400) {
      report.badResponses.push({ status: response.status(), url });
    }
  });
  await page.goto(`${base}/opportunities`, {
    waitUntil: "domcontentloaded",
    timeout: 180_000,
  });
  await page.getByTestId("summary-cards").waitFor({ timeout: 180_000 });
  if (report.badResponses.length) {
    throw new Error(`Bad JS chunks: ${JSON.stringify(report.badResponses)}`);
  }
  report.checks.push({ step: "opportunities_load", ok: true });
  await page.screenshot({
    path: path.join(out, "01-opportunities-videos-tab.png"),
    fullPage: true,
  });
  report.screenshots.push("01-opportunities-videos-tab.png");

  await page.getByRole("button", { name: /Группы для исследования/ }).click();
  await page.getByTestId("patterns-empty").waitFor({ timeout: 30_000 });
  const winnerLink = page.locator('[data-testid="family-feed-winners"] a').first();
  await winnerLink.waitFor({ timeout: 30_000 });
  const href = await winnerLink.getAttribute("href");
  const videoId = decodeURIComponent((href || "").replace(/^.*#winner-/, ""));
  await winnerLink.click();
  await page.waitForFunction(
    (id) => {
      const tab = document.querySelector('[data-testid="metric-winners"]')?.closest("button");
      if (tab?.getAttribute("aria-pressed") !== "true") return false;
      const row = document.getElementById(`winner-${id}`);
      return Boolean(row && !row.closest("[hidden]"));
    },
    videoId,
    { timeout: 30_000 },
  );
  report.checks.push({
    step: "winner_click_from_families",
    videoId,
    href,
    videosTabPressed: true,
  });
  await page.screenshot({
    path: path.join(out, "02-after-winner-link-from-families.png"),
    fullPage: true,
  });
  report.screenshots.push("02-after-winner-link-from-families.png");

  await page.reload({ waitUntil: "domcontentloaded" });
  await page.goto(`${base}/opportunities#winner-${encodeURIComponent(videoId)}`, {
    waitUntil: "domcontentloaded",
  });
  await waitWinnerVisible(page, videoId);
  report.checks.push({ step: "direct_hash_entry", videoId, ok: true });

  await page.getByLabel("Поиск по названию или каналу").fill("zzz-no-match");
  await page.getByText("Видео не найдены").waitFor();
  await page.goto(`${base}/opportunities`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("summary-cards").waitFor({ timeout: 120_000 });
  await page.goto(`${base}/opportunities#winner-${encodeURIComponent(videoId)}`, {
    waitUntil: "domcontentloaded",
  });
  await waitWinnerVisible(page, videoId);
  report.checks.push({ step: "winner_visible_with_search_filter", videoId, ok: true });

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto(`${base}/opportunities`, { waitUntil: "domcontentloaded", timeout: 180_000 });
  await mobile.getByTestId("summary-cards").waitFor({ timeout: 180_000 });
  await mobile.getByRole("button", { name: /Группы для исследования/ }).click();
  await mobile.locator('[data-testid="family-feed-winners"] a').first().click();
  await mobile.waitForFunction(
    (id) => {
      const row = document.getElementById(`winner-${id}`);
      return Boolean(row && !row.closest("[hidden]"));
    },
    videoId,
    { timeout: 30_000 },
  );
  report.checks.push({ step: "mobile_winner_focus", videoId, ok: true });
  await mobile.screenshot({
    path: path.join(out, "03-mobile-winner-focus.png"),
    fullPage: true,
  });
  report.screenshots.push("03-mobile-winner-focus.png");

  await page.goto(
    `${base}/opportunities/families/${encodeURIComponent("family:kw:1505")}`,
    { waitUntil: "domcontentloaded" },
  );
  await page.getByTestId("family-tier-reason").waitFor({ timeout: 60_000 });
  const kwReason = await page.getByTestId("family-tier-reason").innerText();
  report.checks.push({
    step: "family_keyword_detail",
    family_key: "family:kw:1505",
    tierReasonSnippet: kwReason.slice(0, 120),
  });
  await page.screenshot({
    path: path.join(out, "04-family-keyword-detail.png"),
    fullPage: true,
  });
  report.screenshots.push("04-family-keyword-detail.png");

  await page.goto(
    `${base}/opportunities/families/${encodeURIComponent("family:topic:4ac6a6a26765f407")}`,
    { waitUntil: "domcontentloaded" },
  );
  await page.getByTestId("family-tier-reason").waitFor({ timeout: 60_000 });
  const topicReason = await page.getByTestId("family-tier-reason").innerText();
  report.checks.push({
    step: "family_topic_detail",
    family_key: "family:topic:4ac6a6a26765f407",
    tierReasonSnippet: topicReason.slice(0, 120),
  });
  await page.screenshot({
    path: path.join(out, "05-family-topic-detail.png"),
    fullPage: true,
  });
  report.screenshots.push("05-family-topic-detail.png");

  await page.goto(`${base}/validation`, { waitUntil: "domcontentloaded" });
  await page.getByRole("link", { name: /10 Biggest Grain Carts/i }).waitFor({
    timeout: 60_000,
  });
  await page.getByRole("link", { name: /discipline meme/i }).waitFor({
    timeout: 60_000,
  });
  await page.screenshot({
    path: path.join(out, "06-validation-portfolio.png"),
    fullPage: true,
  });
  report.screenshots.push("06-validation-portfolio.png");

  const videoLink = page.getByRole("link", { name: /10 Biggest Grain Carts/i });
  const familyLink = page.getByRole("link", { name: /discipline meme/i });
  const videoHref = await videoLink.getAttribute("href");
  const familyHref = await familyLink.getAttribute("href");
  await videoLink.click();
  await page.waitForURL(/\/saved\/videos\//, { timeout: 30_000 });
  report.checks.push({ step: "validation_video_link", href: videoHref, ok: true });
  await page.goto(`${base}/validation`, { waitUntil: "domcontentloaded" });
  await familyLink.waitFor({ timeout: 30_000 });
  await familyLink.click();
  await page.waitForURL(/\/saved\/families\//, { timeout: 30_000 });
  report.checks.push({ step: "validation_family_link", href: familyHref, ok: true });

  fs.writeFileSync(path.join(out, "acceptance-report.json"), JSON.stringify(report, null, 2));
  await browser.close();
  console.log(JSON.stringify(report, null, 2));
  console.log("fix-2b-winner-link-smoke: OK");
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
