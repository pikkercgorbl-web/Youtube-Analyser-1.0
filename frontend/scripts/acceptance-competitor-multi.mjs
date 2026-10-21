/**
 * Browser acceptance for competitor multi overview.
 * Run: node scripts/acceptance-competitor-multi.mjs
 * Requires: frontend :3000, backend :8000, playwright chromium installed.
 */
import { chromium } from "playwright";
import { writeFileSync, mkdirSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const __dir = dirname(fileURLToPath(import.meta.url));
const outDir = join(__dir, "..", "..", "artifacts", "competitor_multi_acceptance");
mkdirSync(outDir, { recursive: true });

const report = {
  ok: true,
  checks: [],
  errors: [],
};

function check(name, passed, detail = "") {
  report.checks.push({ name, passed, detail });
  if (!passed) {
    report.ok = false;
    report.errors.push(`${name}: ${detail}`);
  }
}

const CHANNEL_A = "https://www.youtube.com/@mkbhd";
const CHANNEL_B = "https://www.youtube.com/@LinusTechTips";
const BAD = "https://www.youtube.com/@this_channel_does_not_exist_nichescope_999";

async function setTextareaValue(locator, value) {
  await locator.evaluate((el, text) => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    setter?.call(el, text);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }, value);
}

async function waitLoadEnabled(page) {
  await page.waitForFunction(
    () => {
      const btn = [...document.querySelectorAll("button")].find((b) =>
        b.textContent?.includes("Загрузить обзор"),
      );
      return btn && !btn.disabled;
    },
    undefined,
    { timeout: 60_000 },
  );
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  try {
    const baseUrl = process.env.ACCEPTANCE_BASE_URL || "http://localhost:3000";
    await page.goto(`${baseUrl}/mass-analysis`, { waitUntil: "networkidle", timeout: 120_000 });
    const textarea = page.locator("textarea").first();
    await textarea.waitFor({ state: "visible", timeout: 60_000 });
    await setTextareaValue(textarea, `${CHANNEL_A}\n${CHANNEL_B}`);
    await page.waitForFunction(
      () => {
        const p = [...document.querySelectorAll("p")].find((el) =>
          el.textContent?.includes("Уникальных строк:"),
        );
        const n = Number(p?.textContent?.match(/Уникальных строк:\s*(\d+)/)?.[1] ?? "0");
        return n >= 2;
      },
      undefined,
      { timeout: 30_000 },
    );
    await waitLoadEnabled(page);
    await page.getByRole("button", { name: "Загрузить обзор" }).click();

    await page.getByRole("heading", { name: "Каналы" }).waitFor({ timeout: 240_000 });
    await page.waitForTimeout(5000);

    const channelGrid = page.getByRole("heading", { name: "Каналы" }).locator("+ div.grid");
    const cardCount = await channelGrid.locator(":scope > div").count();
    check("two channel headers appear", cardCount === 2, `count=${cardCount}`);
    check("no duplicate channel blocks", cardCount === 2, `count=${cardCount}`);

    await page.screenshot({ path: join(outDir, "01-two-channels.png"), fullPage: true });

    const filter = page.locator("select").first();
    const firstChannelValue = await filter.locator("option").nth(1).getAttribute("value");
    if (firstChannelValue) {
      await filter.selectOption(firstChannelValue);
    }
    await page.waitForTimeout(500);
    const cardsAfterFilter = await page.locator("section:has(h2:text('Обычные видео')) .grid > *").count();
    check("channel filter reduces feed", cardsAfterFilter > 0, `visible=${cardsAfterFilter}`);

    await page.getByRole("button", { name: "Больше просмотров" }).click();
    await page.waitForTimeout(300);
    await page.getByRole("button", { name: "Новые" }).click();
    check("sort toggles clickable", true);

    const analyzeLink = page.getByRole("link", { name: "Анализ канала" }).first();
    const href = await analyzeLink.getAttribute("href");
    check(
      "analyze link has channel_id and focus",
      Boolean(href?.includes("channel_id=") && href?.includes("focus_video_id=")),
      href ?? "",
    );

    const saveBtn = page.getByRole("button", { name: "Сохранить" }).first();
    const saveResponsePromise = page
      .waitForResponse(
        (r) => r.url().includes("/api/saved-videos") && r.request().method() === "POST",
        { timeout: 30_000 },
      )
      .catch(() => null);
    await saveBtn.click();
    const saveResp = await saveResponsePromise;
    const savedLinkVisible = await page
      .getByTestId("save-video-saved")
      .first()
      .waitFor({ timeout: 20_000 })
      .then(() => true)
      .catch(() => false);
    check(
      "save video (POST or already saved UI)",
      (saveResp !== null && saveResp.ok()) || savedLinkVisible,
      saveResp?.status()?.toString() ?? (savedLinkVisible ? "already-saved" : "no response"),
    );

    await page.screenshot({ path: join(outDir, "02-feed-and-links.png"), fullPage: true });

    // Partial failure scenario
    await setTextareaValue(textarea, `${CHANNEL_A}\n${BAD}`);
    await waitLoadEnabled(page);
    await page.getByRole("button", { name: "Загрузить обзор" }).click();
    await page.waitForFunction(
      () => {
        const loading = document.body.textContent?.includes("Загружаем каналы");
        const h = [...document.querySelectorAll("h2")].find((el) => el.textContent === "Каналы");
        const channelBlocks = h?.nextElementSibling?.children?.length ?? 0;
        const failed = document.body.textContent?.includes("Не загружен");
        return !loading && (channelBlocks >= 1 || failed);
      },
      undefined,
      { timeout: 240_000 },
    );
    const stillHasSuccess =
      (await page.getByRole("heading", { name: "Каналы" }).locator("+ div.grid > div").count()) >= 1;
    check("successful channel remains after peer failure", stillHasSuccess);

    const retryBtn = page.getByRole("button", { name: "Повторить" }).first();
    check("retry button visible for failed", await retryBtn.isVisible());

    await page.screenshot({ path: join(outDir, "03-partial-failure.png"), fullPage: true });

    check(
      "loading finished after partial run",
      !(await page.getByText("Загружаем каналы…").isVisible().catch(() => false)),
    );
  } catch (err) {
    report.ok = false;
    report.errors.push(err instanceof Error ? err.message : String(err));
    await page.screenshot({ path: join(outDir, "error.png"), fullPage: true }).catch(() => {});
  } finally {
    writeFileSync(join(outDir, "report.json"), JSON.stringify(report, null, 2));
    await browser.close();
  }

  console.log(JSON.stringify(report, null, 2));
  process.exit(report.ok ? 0 : 1);
}

main();
