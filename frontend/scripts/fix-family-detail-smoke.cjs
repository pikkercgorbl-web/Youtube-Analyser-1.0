/**
 * Family detail browser smoke — :3100 (.next-acceptance).
 * Usage: node frontend/scripts/fix-family-detail-smoke.cjs [before|after]
 */
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = process.env.SMOKE_BASE_URL || "http://127.0.0.1:3100";
const API = process.env.SMOKE_API_URL || "http://127.0.0.1:8000";
const phase = process.argv[2] === "before" ? "before" : "after";
const OUT = path.join(
  __dirname,
  "..",
  "..",
  "artifacts",
  `fix_family_detail_screenshots_${phase}`,
);

const MINECRAFT_FAMILY = process.env.SMOKE_FAMILY_MINECRAFT || "family:kw:1497";
const SMALL_FAMILY = process.env.SMOKE_FAMILY_SMALL || "family:kw:181";

async function apiJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} ${res.status}`);
  return res.json();
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, name), fullPage: true });
}

async function exerciseFamily(page, familyKey, tag) {
  const url = `${BASE}/opportunities/families/${encodeURIComponent(familyKey)}`;
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.getByTestId("family-detail-header").waitFor({ timeout: 30000 });
  await page
    .getByTestId("family-member-card")
    .first()
    .waitFor({ timeout: 30000 })
    .catch(() => {});
  await page.waitForTimeout(400);
  await shot(page, `${tag}-overview.png`);

  const yt = page.locator('a[aria-label*="YouTube"]').first();
  if ((await yt.count()) > 0) {
    await yt.focus();
  }

  const detailBtn = page.getByRole("link", { name: "Детали видео" }).first();
  if ((await detailBtn.count()) > 0) {
    await detailBtn.click();
    await page.waitForURL(/\/opportunities\/videos\//, { timeout: 15000 });
    await shot(page, `${tag}-video-detail.png`);
    await page.goBack({ waitUntil: "domcontentloaded" });
    await page.getByTestId("family-detail-header").waitFor({ timeout: 15000 });
  }

  const diagSummary = page.locator("summary").filter({ hasText: /Как сформирована подборка/i });
  if ((await diagSummary.count()) > 0) {
    await diagSummary.first().click();
    await page.waitForTimeout(300);
    await shot(page, `${tag}-diagnostic-open.png`);
  }

  const save = page.getByTestId("save-family").or(page.getByTestId("save-video"));
  return {
    familyKey,
    url,
    detailLinks: await page.getByRole("link", { name: "Детали видео" }).count(),
    members: await page
      .getByTestId("family-member-card")
      .or(page.getByTestId("pattern-member"))
      .count(),
    saveControls: await save.count(),
  };
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  await apiJson(`${API}/api/attention/pattern-families/${encodeURIComponent(MINECRAFT_FAMILY)}`);

  const browser = await chromium.launch();
  const report = { phase, base: BASE, checks: [] };

  for (const viewport of [
    { width: 1280, height: 900, tag: "desktop" },
    { width: 390, height: 844, tag: "390px" },
  ]) {
    const page = await browser.newPage({ viewport });
    report.checks.push({
      viewport: viewport.tag,
      minecraft: await exerciseFamily(page, MINECRAFT_FAMILY, `minecraft-${viewport.tag}`),
      small: await exerciseFamily(page, SMALL_FAMILY, `small-${viewport.tag}`),
    });
    await page.close();
  }

  fs.writeFileSync(path.join(OUT, "acceptance-report.json"), JSON.stringify(report, null, 2));
  await browser.close();
  console.log(JSON.stringify(report, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
