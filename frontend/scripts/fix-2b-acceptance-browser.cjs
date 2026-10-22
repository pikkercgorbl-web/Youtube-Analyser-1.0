/**
 * Fix 2B acceptance — live UI against local dev (real API proxy).
 * Usage: node scripts/fix-2b-acceptance-browser.cjs
 */
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");

const base = process.env.RADAR_ACCEPTANCE_URL || "http://127.0.0.1:3000";
const out = path.resolve(
  process.env.RADAR_SCREENSHOT_DIR ||
    path.join(__dirname, "../../artifacts/fix_2b_acceptance_screenshots"),
);
fs.mkdirSync(out, { recursive: true });

async function isWinnerRowVisible(page, videoId) {
  return page.evaluate((id) => {
    const row = document.getElementById(`winner-${id}`);
    if (!row) return false;
    const hiddenAncestor = row.closest("[hidden]");
    if (hiddenAncestor) return false;
    const rect = row.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }, videoId);
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {}),
  });
  const report = { base, checks: [], screenshots: [] };

  const desktop = await browser.newPage({
    viewport: { width: 1440, height: 900 },
  });
  await desktop.goto(`${base}/opportunities`, { waitUntil: "networkidle" });
  await desktop.getByTestId("summary-cards").waitFor({ timeout: 60_000 });
  await desktop.screenshot({
    path: path.join(out, "01-opportunities-videos-tab.png"),
    fullPage: true,
  });
  report.screenshots.push("01-opportunities-videos-tab.png");

  await desktop.getByRole("button", { name: /Группы для исследования/ }).click();
  await desktop.getByTestId("patterns-empty").waitFor({ timeout: 30_000 });
  const winnerLink = desktop.locator('[data-testid="family-feed-winners"] a').first();
  const winnerHref = await winnerLink.getAttribute("href");
  assert.match(winnerHref || "", /#winner-/);
  const videoId = decodeURIComponent(
    (winnerHref || "").replace(/^.*#winner-/, ""),
  );
  report.checks.push({ step: "family_winner_link", videoId, href: winnerHref });

  await winnerLink.click();
  await desktop.waitForFunction(
    (id) => {
      const videosTab = document.querySelector(
        'button[aria-pressed="true"]',
      );
      if (!videosTab || !/Видео для разведки/.test(videosTab.textContent || "")) {
        return false;
      }
      const row = document.getElementById(`winner-${id}`);
      if (!row || row.closest("[hidden]")) return false;
      const rect = row.getBoundingClientRect();
      return rect.height > 0;
    },
    videoId,
    { timeout: 15_000 },
  );
  report.checks.push({ step: "winner_visible_after_click", videoId, ok: true });
  await desktop.screenshot({
    path: path.join(out, "02-after-winner-link-from-families.png"),
    fullPage: true,
  });
  report.screenshots.push("02-after-winner-link-from-families.png");

  await desktop.reload({ waitUntil: "networkidle" });
  await desktop.goto(`${base}/opportunities${winnerHref}`, {
    waitUntil: "networkidle",
  });
  await desktop.waitForFunction(
    (id) => {
      const row = document.getElementById(`winner-${id}`);
      return Boolean(row && !row.closest("[hidden]"));
    },
    videoId,
    { timeout: 15_000 },
  );
  report.checks.push({ step: "winner_visible_after_reload_with_hash", ok: true });

  await desktop.getByLabel("Поиск по названию или каналу").fill("zzz-no-match");
  await desktop.getByText("Видео не найдены").waitFor();
  await desktop.goto(`${base}/opportunities${winnerHref}`, {
    waitUntil: "networkidle",
  });
  await desktop.waitForFunction(
    (id) => {
      const input = document.querySelector(
        'input[aria-label="Поиск по названию или каналу"]',
      );
      const row = document.getElementById(`winner-${id}`);
      return Boolean(row && !row.closest("[hidden]") && input);
    },
    videoId,
    { timeout: 15_000 },
  );
  report.checks.push({ step: "winner_visible_with_active_filter", ok: true });

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto(`${base}/opportunities`, { waitUntil: "networkidle" });
  await mobile.getByRole("button", { name: /Группы для исследования/ }).click();
  const mobileWinner = mobile.locator('[data-testid="family-feed-winners"] a').first();
  await mobileWinner.click();
  await mobile.waitForFunction(
    (id) => {
      const row = document.getElementById(`winner-${id}`);
      return Boolean(row && !row.closest("[hidden]"));
    },
    videoId,
    { timeout: 15_000 },
  );
  await mobile.screenshot({
    path: path.join(out, "03-mobile-winner-focus.png"),
    fullPage: true,
  });
  report.screenshots.push("03-mobile-winner-focus.png");
  report.checks.push({ step: "mobile_winner_focus", ok: true });

  await desktop.goto(
    `${base}/opportunities/families/${encodeURIComponent("family:kw:1505")}`,
    { waitUntil: "networkidle" },
  );
  await desktop.getByTestId("family-tier-reason").waitFor({ timeout: 30_000 });
  await desktop.screenshot({
    path: path.join(out, "04-family-keyword-detail.png"),
    fullPage: true,
  });
  report.screenshots.push("04-family-keyword-detail.png");

  await desktop.goto(
    `${base}/opportunities/families/${encodeURIComponent("family:topic:4ac6a6a26765f407")}`,
    { waitUntil: "networkidle" },
  );
  await desktop.getByTestId("family-tier-reason").waitFor({ timeout: 30_000 });
  await desktop.screenshot({
    path: path.join(out, "05-family-topic-detail.png"),
    fullPage: true,
  });
  report.screenshots.push("05-family-topic-detail.png");

  await desktop.goto(`${base}/validation`, { waitUntil: "networkidle" });
  await desktop.screenshot({
    path: path.join(out, "06-validation-portfolio.png"),
    fullPage: true,
  });
  report.screenshots.push("06-validation-portfolio.png");
  const validationText = await desktop.locator("body").innerText();
  report.checks.push({
    step: "validation_smoke",
    hasSavedVideo: /SavedVideo|сохранённ.*видео/i.test(validationText),
    bodySnippet: validationText.slice(0, 500),
  });

  fs.writeFileSync(
    path.join(out, "acceptance-report.json"),
    JSON.stringify(report, null, 2),
  );
  await browser.close();
  console.log(JSON.stringify(report, null, 2));
  console.log(`Screenshots: ${out}`);
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
