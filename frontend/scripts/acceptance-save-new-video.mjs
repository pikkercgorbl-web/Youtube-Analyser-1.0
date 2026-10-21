/**
 * Save a fresh video from competitor overview.
 * node scripts/acceptance-save-new-video.mjs
 */
import { chromium } from "playwright";

const BASE = process.env.ACCEPTANCE_BASE_URL || "http://localhost:3000";
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const CHANNEL_REFS = [
  "https://www.youtube.com/@LinusTechTips",
  "https://www.youtube.com/@mkbhd",
  "https://www.youtube.com/@MrBeast",
];

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

async function listSavedVideoIds() {
  const resp = await fetch(`${API}/api/saved-videos?archived=all`);
  if (!resp.ok) return new Set();
  const data = await resp.json();
  return new Set((data.items ?? []).map((it) => it.video_id).filter(Boolean));
}

async function findUnsavedVideoId(saved) {
  for (const channel_ref of CHANNEL_REFS) {
    const resp = await fetch(`${API}/api/analysis/competitors/channel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel_ref }),
    });
    if (!resp.ok) continue;
    const data = await resp.json();
    for (const pub of data.publications ?? []) {
      if (pub.video_id && !saved.has(pub.video_id)) {
        return { videoId: pub.video_id, channel_ref };
      }
    }
  }
  return null;
}

async function countSavedRows(videoId) {
  const resp = await fetch(`${API}/api/saved-videos?archived=all`);
  const data = await resp.json();
  return (data.items ?? []).filter((it) => it.video_id === videoId).length;
}

async function main() {
  const savedBefore = await listSavedVideoIds();
  const target = await findUnsavedVideoId(savedBefore);
  const report = {
    ok: false,
    videoId: target?.videoId ?? null,
    postStatuses: [],
    idempotentSecondPost: null,
    savedListCount: 0,
    savedPageHasVideo: false,
  };

  if (!target) {
    report.error = "No unsaved video_id found via preview API";
    console.log(JSON.stringify(report, null, 2));
    process.exit(1);
  }

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    page.on("response", (r) => {
      const isSavePost =
        r.request().method() === "POST" &&
        (r.url().includes("/api/saved-videos") ||
          r.url().includes("/api/manual-search/save-video"));
      if (isSavePost) report.postStatuses.push(r.status());
    });

    const peer = CHANNEL_REFS.find((r) => r !== target.channel_ref) ?? CHANNEL_REFS[0];
    await page.goto(`${BASE}/mass-analysis`, { waitUntil: "networkidle", timeout: 120_000 });
    const textarea = page.locator("textarea").first();
    await setTextareaValue(textarea, `${target.channel_ref}\n${peer}`);
    await page.waitForFunction(
      () =>
        Number(
          [...document.querySelectorAll("p")]
            .find((el) => el.textContent?.includes("Уникальных строк:"))
            ?.textContent?.match(/Уникальных строк:\s*(\d+)/)?.[1] ?? 0,
        ) >= 2,
      undefined,
      { timeout: 30_000 },
    );
    await page.getByRole("button", { name: "Загрузить обзор" }).click();
    await page.getByRole("heading", { name: "Каналы" }).waitFor({ timeout: 240_000 });

    const card = page
      .locator("div.p-3")
      .filter({ has: page.locator(`a[href*="focus_video_id=${target.videoId}"]`) });
    await card.getByTestId("save-video").waitFor({ timeout: 120_000 });
    await card.getByTestId("save-video").click();
    await card.getByTestId("save-video-saved").waitFor({ timeout: 120_000 });

    const postsAfterUiSave = report.postStatuses.length;

    const dupResp = await fetch(`${API}/api/manual-search/save-video`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_id: target.videoId }),
    });
    report.idempotentSecondPost = {
      status: dupResp.status,
      body: await dupResp.json().catch(() => null),
    };

    report.savedListCount = await countSavedRows(target.videoId);

    await page.goto(`${BASE}/saved`, { waitUntil: "networkidle", timeout: 120_000 });
    report.savedPageHasVideo = (await page.content()).includes(target.videoId);

    report.ok =
      report.postStatuses.length >= 1 &&
      report.postStatuses[0] >= 200 &&
      report.postStatuses[0] < 300 &&
      report.savedListCount === 1 &&
      report.savedPageHasVideo &&
      postsAfterUiSave === 1 &&
      report.idempotentSecondPost.status === 200 &&
      report.idempotentSecondPost.body?.idempotent === true;
  } catch (err) {
    report.error = err instanceof Error ? err.message : String(err);
  }

  console.log(JSON.stringify(report, null, 2));
  await browser.close();
  process.exit(report.ok ? 0 : 1);
}

main();
