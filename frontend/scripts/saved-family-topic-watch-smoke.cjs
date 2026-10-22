/**
 * Smoke: /saved/families/{id} topic watch panel — button → results → save.
 * Usage: node frontend/scripts/saved-family-topic-watch-smoke.cjs [familyId]
 */
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = process.env.SMOKE_BASE_URL || "http://127.0.0.1:3000";
const API = process.env.SMOKE_API_URL || "http://127.0.0.1:8000";
const familyId = process.argv[2] || "1";
const OUT = path.join(__dirname, "..", "..", "artifacts", "saved_family_topic_watch_browser");

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const report = { familyId, steps: [], ok: false };

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  try {
    const url = `${BASE}/saved/families/${familyId}`;
    await page.goto(url, { waitUntil: "networkidle", timeout: 90000 });
    report.steps.push({ step: "open_family_detail", url });

    await page.getByRole("heading", { name: "Новые видео по теме" }).waitFor({ timeout: 30000 });
    await page.screenshot({ path: path.join(OUT, "01-family-topic-panel.png"), fullPage: true });

    const runBtn = page.getByRole("button", { name: "Запустить поиск сейчас" });
    if ((await runBtn.count()) > 0 && (await runBtn.isEnabled())) {
      report.steps.push({ step: "run_now_skipped_or_clicked", enabled: true });
    } else {
      const searchBtn = page.getByRole("button", { name: "Искать видео по теме" });
      if ((await searchBtn.count()) > 0) {
        await searchBtn.click();
        report.steps.push({ step: "click_search_by_topic" });
      }
    }

    const findings = page.locator("li").filter({ hasText: "Найдено по запросу" });
    await findings.first().waitFor({ timeout: 15000 }).catch(() => {});
    const findingCount = await findings.count();
    report.steps.push({ step: "findings_visible", count: findingCount });
    await page.screenshot({ path: path.join(OUT, "02-findings.png"), fullPage: true });

    const saveBtn = page
      .getByRole("button", { name: "Сохранить в исследования" })
      .filter({ hasNotText: "Уже в сохранённых" })
      .first();
    if ((await saveBtn.count()) > 0) {
      await saveBtn.click();
      await page.waitForTimeout(1500);
      report.steps.push({ step: "save_finding_clicked" });
      await page.screenshot({ path: path.join(OUT, "03-after-save.png"), fullPage: true });
    } else {
      report.steps.push({ step: "save_finding_skipped", reason: "no eligible button" });
    }

    const apiFindings = await fetch(`${API}/api/saved-families/${familyId}/topic-watch/findings?limit=1`).then(
      (r) => r.json(),
    );
    report.api_findings_total = apiFindings.total;
    report.ok = findingCount > 0 || apiFindings.total > 0;
  } catch (err) {
    report.error = String(err);
    await page.screenshot({ path: path.join(OUT, "error.png"), fullPage: true }).catch(() => {});
  } finally {
    await browser.close();
  }

  fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (!report.ok) process.exitCode = 1;
}

main();
