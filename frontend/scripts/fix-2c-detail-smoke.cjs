/**
 * Fix 2C browser smoke — prod on :3100, desktop + 390px.
 * Usage: node frontend/scripts/fix-2c-detail-smoke.cjs
 */
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = process.env.SMOKE_BASE_URL || "http://127.0.0.1:3100";
const API = process.env.SMOKE_API_URL || "http://127.0.0.1:8000";
const OUT = path.join(__dirname, "..", "..", "artifacts", "fix_2c_screenshots");

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
  const families = await apiJson(`${API}/api/attention/pattern-families?limit=50`);
  const videos = await apiJson(`${API}/api/attention/videos?limit=5`);
  const keywordFamily = (families.items || []).find(
    (f) => f.opportunity_presentation_tier === "search_collection",
  );
  const topicFamily = (families.items || []).find(
    (f) => f.grouping_basis_kind === "metadata_topic" || f.family_kind === "video_topic",
  );
  const winnerId = videos.items?.[0]?.video_id;

  const browser = await chromium.launch();
  const report = { base: BASE, winnerId, keywordFamily: keywordFamily?.family_key, topicFamily: topicFamily?.family_key, checks: [] };

  for (const viewport of [
    { width: 1280, height: 900, tag: "desktop" },
    { width: 390, height: 844, tag: "390px" },
  ]) {
    const page = await browser.newPage({ viewport });
    await page.goto(`${BASE}/opportunities`, { waitUntil: "networkidle" });
    await shot(page, `01-opportunities-${viewport.tag}.png`);

    if (winnerId) {
      await page.goto(`${BASE}/opportunities#winner-${encodeURIComponent(winnerId)}`, {
        waitUntil: "networkidle",
      });
      await page.waitForTimeout(800);
      const baseline = page.getByTestId("baseline-available").or(page.getByTestId("baseline-unavailable"));
      report.checks.push({ viewport: viewport.tag, winnerBaseline: await baseline.count() });
      await shot(page, `02-winner-${viewport.tag}.png`);
    }

    if (keywordFamily?.family_key) {
      await page.goto(
        `${BASE}/opportunities/families/${encodeURIComponent(keywordFamily.family_key)}`,
        { waitUntil: "networkidle" },
      );
      await page.getByText(/Ролики подборки для ручного сравнения/i).waitFor({ timeout: 15000 });
      await shot(page, `03-keyword-family-${viewport.tag}.png`);
    }

    if (topicFamily?.family_key && topicFamily.family_key !== keywordFamily?.family_key) {
      await page.goto(
        `${BASE}/opportunities/families/${encodeURIComponent(topicFamily.family_key)}`,
        { waitUntil: "networkidle" },
      );
      await shot(page, `04-topic-family-${viewport.tag}.png`);
    }

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
