const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

const base = process.env.RADAR_ACCEPTANCE_URL || "http://127.0.0.1:3100";
const out = path.resolve(__dirname, "../../artifacts/fix_3b_acceptance_screenshots");
fs.mkdirSync(out, { recursive: true });

(async () => {
  const report = {
    base,
    checks: [],
    badResponses: [],
    consoleErrors: [],
    httpSamples: [],
    screenshots: [],
  };
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      report.consoleErrors.push(msg.text());
    }
  });
  page.on("response", async (response) => {
    const url = response.url();
    if (url.includes("/_next/static/") && response.status() >= 400) {
      report.badResponses.push({ status: response.status(), url });
    }
    if (
      url.includes("/api/keywords/pool-summary") ||
      url.includes("/api/monitoring/cycles")
    ) {
      let body = null;
      try {
        body = await response.json();
      } catch {
        body = null;
      }
      report.httpSamples.push({
        status: response.status(),
        url: url.replace(/^https?:\/\/[^/]+/, ""),
        bodyPreview:
          body && typeof body === "object"
            ? JSON.stringify(body).slice(0, 400)
            : null,
      });
    }
  });

  await page.goto(`${base}/keywords`, {
    waitUntil: "domcontentloaded",
    timeout: 180_000,
  });
  await page.getByTestId("keyword-pool-queue-context").waitFor({ timeout: 120_000 });
  const queueText = await page.getByTestId("keyword-pool-queue-context").innerText();
  report.checks.push({
    step: "keywords_queue_context",
    ok: /24 ч/i.test(queueText) && /Пора просканировать|worker/i.test(queueText),
    snippet: queueText.slice(0, 200),
  });
  await page.screenshot({
    path: path.join(out, "01-keywords-queue-context.png"),
    fullPage: false,
    timeout: 120_000,
  });
  report.screenshots.push("01-keywords-queue-context.png");

  await page.goto(`${base}/monitoring`, {
    waitUntil: "domcontentloaded",
    timeout: 180_000,
  });
  await page.getByText("Недавние циклы").waitFor({ timeout: 120_000 });
  await page.getByText("Нет в API").waitFor({ timeout: 60_000 });
  await page.getByText("Ошибки захвата").waitFor({ timeout: 60_000 });
  const latestPartial = report.httpSamples.find((s) =>
    s.url.includes("/api/monitoring/cycles"),
  );
  report.checks.push({
    step: "monitoring_cycle_columns",
    ok: true,
    cyclesApiStatus: latestPartial?.status ?? null,
  });
  report.checks.push({
    step: "no_console_errors",
    ok: report.consoleErrors.length === 0,
    consoleErrors: report.consoleErrors.slice(0, 5),
  });
  await page.screenshot({
    path: path.join(out, "02-monitoring-cycles-partial-columns.png"),
    fullPage: false,
    timeout: 120_000,
  });
  report.screenshots.push("02-monitoring-cycles-partial-columns.png");

  if (report.badResponses.length) {
    report.ok = false;
    report.error = `Bad JS chunks: ${JSON.stringify(report.badResponses)}`;
  } else {
    report.ok = report.checks.every((c) => c.ok !== false);
  }

  fs.writeFileSync(path.join(out, "acceptance-report.json"), JSON.stringify(report, null, 2));
  await browser.close();
  if (!report.ok) {
    console.error(JSON.stringify(report, null, 2));
    process.exit(1);
  }
  console.log(JSON.stringify(report, null, 2));
})();
