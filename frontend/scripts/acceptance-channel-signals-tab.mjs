/**
 * Screenshot /opportunities «Сигналы по каналам» tab (desktop + 390px).
 * Prefetches Attention API in Node (works in sandbox), then mocks browser XHR to localhost:8000.
 */
import { mkdir, writeFile } from "node:fs/promises";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = join(__dirname, "../../artifacts/channel_signals_tab_acceptance");
const API = "http://localhost:8000";

async function fetchJson(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json();
}

async function loadAttentionPayload() {
  const [summary, videos, families, channels] = await Promise.all([
    fetchJson("/api/attention/summary"),
    fetchJson("/api/attention/videos?limit=50"),
    fetchJson("/api/attention/pattern-families?limit=100"),
    fetchJson("/api/attention/channels?limit=50"),
  ]);
  return { summary, videos, families, channels };
}

async function main() {
  await mkdir(outDir, { recursive: true });
  const payload = await loadAttentionPayload();
  await writeFile(
    join(outDir, "acceptance-report.json"),
    JSON.stringify(
      {
        captured_at: new Date().toISOString(),
        channel_count: payload.channels.items?.length ?? 0,
        categories: payload.channels.items?.map((c) => ({
          title: c.channel_title,
          ratio: c.recent_median_vph_vs_previous,
        })),
      },
      null,
      2,
    ),
  );

  const browser = await chromium.launch({ channel: "msedge" });
  const base = process.env.ACCEPTANCE_BASE_URL || "http://localhost:3006/opportunities";

  const routes = [
    ["/api/attention/summary", payload.summary],
    ["/api/attention/videos", payload.videos],
    ["/api/attention/pattern-families", payload.families],
    ["/api/attention/channels", payload.channels],
  ];

  for (const { name, width, height } of [
    { name: "desktop", width: 1280, height: 900 },
    { name: "mobile-390", width: 390, height: 844 },
  ]) {
    const page = await browser.newPage({ viewport: { width, height } });
    await page.route(`${API}/api/**`, (route) => {
      const url = new URL(route.request().url());
      const hit = routes.find(([path]) => url.pathname === path);
      if (!hit) {
        return route.continue();
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(hit[1]),
      });
    });
    page.on("console", (msg) => console.log(`[${name} console]`, msg.text()));
    page.on("requestfailed", (req) =>
      console.log(`[${name} reqfail]`, req.url(), req.failure()?.errorText),
    );
    await page.goto(base, { waitUntil: "domcontentloaded", timeout: 120_000 });
    try {
      await page.getByTestId("snapshot-meta").waitFor({ timeout: 60_000 });
    } catch (e) {
      await page.screenshot({ path: join(outDir, `channels-tab-${name}-debug.png`), fullPage: true });
      const text = await page.locator("body").innerText();
      console.log(`[${name} body]`, text.slice(0, 500));
      throw e;
    }
    await page.locator('button:has([data-testid="metric-channels"])').click();
    await page
      .getByTestId("channels-category-summary")
      .or(page.getByTestId("channels-empty"))
      .waitFor({ timeout: 30_000 });
    await page.waitForTimeout(500);
    const cardCount = await page.getByTestId("channel-card").count();
    await page.screenshot({
      path: join(outDir, `channels-tab-${name}.png`),
      fullPage: true,
    });
    console.log(JSON.stringify({ viewport: name, cardCount }));
    await page.close();
  }

  await browser.close();
  console.log(`Saved to ${outDir}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
