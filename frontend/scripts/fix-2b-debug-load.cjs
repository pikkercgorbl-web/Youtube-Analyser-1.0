const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on("response", (r) => {
    if (r.url().includes("/api/attention")) {
      console.log("api", r.status(), r.url().slice(0, 80));
    }
  });
  const base = process.env.RADAR_ACCEPTANCE_URL || "http://127.0.0.1:3100";
  await page.goto(`${base}/opportunities`, {
    waitUntil: "domcontentloaded",
  });
  for (let i = 0; i < 24; i += 1) {
    const has = await page.getByTestId("summary-cards").isVisible().catch(() => false);
    const loading = await page.getByText("Ищем сохранённые находки").isVisible().catch(() => false);
    const err = await page.getByTestId("error-state").isVisible().catch(() => false);
    console.log("tick", i, { has, loading, err });
    if (has || err) break;
    await page.waitForTimeout(5000);
  }
  console.log(await page.locator("body").innerText().then((t) => t.slice(0, 800)));
  await browser.close();
})();
