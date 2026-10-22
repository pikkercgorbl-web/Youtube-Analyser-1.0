/**
 * Winner detail browser smoke — prod on :3100 (.next-acceptance).
 * Usage: node frontend/scripts/fix-winner-detail-smoke.cjs
 */
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = process.env.SMOKE_BASE_URL || "http://127.0.0.1:3100";
const API = process.env.SMOKE_API_URL || "http://127.0.0.1:8000";
const OUT = path.join(__dirname, "..", "..", "artifacts", "fix_winner_detail_screenshots");

async function apiJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} ${res.status}`);
  return res.json();
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, name), fullPage: true });
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const videos = await apiJson(`${API}/api/attention/videos?limit=3`);
  const winnerId = videos.items?.[0]?.video_id;
  if (!winnerId) {
    throw new Error("No winners in snapshot");
  }
  await apiJson(`${API}/api/attention/videos/${encodeURIComponent(winnerId)}`);

  const browser = await chromium.launch();
  const report = { base: BASE, winnerId, checks: [] };

  for (const viewport of [
    { width: 1280, height: 900, tag: "desktop" },
    { width: 390, height: 844, tag: "390px" },
  ]) {
    const page = await browser.newPage({ viewport });
    await page.goto(`${BASE}/opportunities`, { waitUntil: "networkidle" });
    const detailLink = page.getByTestId("winner-detail-link").first();
    await detailLink.waitFor({ timeout: 20000 });
    await detailLink.click();
    await page.waitForURL(/\/opportunities\/videos\//, { timeout: 15000 });
    await page.getByText(/Почему видео в Winners/i).waitFor({ timeout: 15000 });
    const baseline = page
      .getByTestId("baseline-available")
      .or(page.getByTestId("baseline-unavailable"));
    report.checks.push({
      viewport: viewport.tag,
      detailUrl: page.url(),
      baseline: await baseline.count(),
    });
    await shot(page, `winner-detail-${viewport.tag}.png`);

    await page.goto(
      `${BASE}/opportunities/videos/${encodeURIComponent(winnerId)}`,
      { waitUntil: "networkidle" },
    );
    await page.getByTestId("winner-detail-back").waitFor({ timeout: 15000 });
    await shot(page, `winner-detail-direct-${viewport.tag}.png`);
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
