/**
 * Render the three visual directions to PNGs and assert the basics.
 *
 *   npm i --no-save playwright-core
 *   npx vite --host 127.0.0.1 --port 5175 &
 *   node scripts/shoot-directions.mjs http://127.0.0.1:5175
 *
 * Chromium comes from the machine's playwright cache; pass PLAYWRIGHT_CHROMIUM
 * to point at a specific binary.
 */

import { mkdir, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const base = process.argv[2] ?? "http://127.0.0.1:5175";
const outDir =
  process.argv[3] ??
  join(homedir(), ".capy", "drive", "captain-happyclaw", "renders", "HAPA-20");

const cache = join(homedir(), "AppData", "Local", "ms-playwright");
const candidates = [
  process.env.PLAYWRIGHT_CHROMIUM,
  ...["chromium-1255", "chromium-1244", "chromium-1243", "chromium-1223"].map((build) =>
    join(cache, build, "chrome-win64", "chrome.exe"),
  ),
].filter(Boolean);

const executablePath = candidates.find((path) => existsSync(path));
if (!executablePath) {
  throw new Error(`no chromium found, looked in: ${candidates.join(", ")}`);
}

const shots = [];
for (const dir of ["a", "b", "c"]) {
  for (const pageId of ["chat", "design"]) {
    for (const theme of ["dark", "light"]) {
      shots.push({
        path: `/directions/${dir}/${pageId}`,
        file: `direction-${dir}-${pageId}-${theme}.png`,
        theme,
        viewport: { width: 1440, height: 900 },
        dir,
        pageId,
      });
    }
  }
  for (const theme of ["dark", "light"]) {
    shots.push({
      path: `/directions/${dir}/chat`,
      file: `direction-${dir}-chat-${theme}-390.png`,
      theme,
      viewport: { width: 390, height: 844 },
      dir,
      pageId: "chat-mobile",
    });
  }
}

await mkdir(outDir, { recursive: true });

const browser = await chromium.launch({ executablePath, headless: true });
const results = [];

for (const shot of shots) {
  const context = await browser.newContext({
    viewport: shot.viewport,
    colorScheme: shot.theme,
    deviceScaleFactor: 1,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
  });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(String(error)));

  await page.goto(base + shot.path, { waitUntil: "networkidle" });
  await page.waitForSelector("h1, header", { timeout: 15000 });
  await page.waitForTimeout(350);

  const metrics = await page.evaluate(() => ({
    theme: document.documentElement.classList.contains("dark") ? "dark" : "light",
    direction: document.documentElement.dataset.direction ?? null,
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    bodyText: document.body.innerText.length,
  }));

  await page.screenshot({ path: join(outDir, shot.file) });
  results.push({
    ...shot,
    file: join(outDir, shot.file),
    errors,
    ...metrics,
    overflow: metrics.scrollWidth > metrics.clientWidth + 1,
    ok: errors.length === 0 && !(metrics.scrollWidth > metrics.clientWidth + 1),
  });
  await context.close();
}

await browser.close();
await writeFile(
  join(outDir, "verification.json"),
  JSON.stringify({ base, ranAt: new Date().toISOString(), results }, null, 2),
);

const failed = results.filter((result) => !result.ok);
for (const result of results) {
  const flag = result.ok ? "ok  " : "FAIL";
  console.log(
    `${flag} ${result.file.split(/[\\/]/).pop()}  theme=${result.theme} dir=${result.direction} ` +
      `scroll=${result.scrollWidth}/${result.clientWidth} err=${result.errors.length}`,
  );
  if (result.errors.length > 0) console.log("      " + result.errors.join("\n      "));
}
process.exit(failed.length === 0 ? 0 : 1);
