/**
 * Programmatic check of the three directions: font resolution, contrast,
 * minimum type size, layout boxes and mobile tap targets. Complements the PNGs
 * in renders/HAPA-20, since screenshots do not tell you a contrast ratio.
 *
 *   node scripts/audit-directions.mjs http://127.0.0.1:5175
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
const executablePath = ["chromium-1255", "chromium-1244", "chromium-1243", "chromium-1223"]
  .map((build) => join(cache, build, "chrome-win64", "chrome.exe"))
  .find((path) => existsSync(path));
if (!executablePath) throw new Error("no chromium found");

const PAIRS = [
  ["正文 / 面板", "--hc-fg-default", "--hc-bg-surface"],
  ["正文 / 画布", "--hc-fg-default", "--hc-bg-canvas"],
  ["次级 / 面板", "--hc-fg-muted", "--hc-bg-surface"],
  ["次级 / 画布", "--hc-fg-muted", "--hc-bg-canvas"],
  ["弱化 / 面板", "--hc-fg-subtle", "--hc-bg-surface"],
  ["强调字 / 强调底", "--hc-accent-fg", "--hc-accent-soft"],
  ["按钮字 / 按钮底", "--hc-fg-onaccent", "--hc-accent-default"],
  ["危险 / 面板", "--hc-danger-default", "--hc-bg-surface"],
];

await mkdir(outDir, { recursive: true });
const browser = await chromium.launch({ executablePath, headless: true });
const report = [];

for (const dir of ["a", "b", "c"]) {
  for (const theme of ["dark", "light"]) {
    const agentContext = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      colorScheme: theme,
      locale: "zh-CN",
    });
    const page = await agentContext.newPage();
    const errors = [];
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("pageerror", (error) => errors.push(String(error)));
    await page.goto(`${base}/directions/${dir}/chat`, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);

    const desktop = await page.evaluate((pairs) => {
      const rgb = (value) => {
        const probe = document.createElement("div");
        probe.style.color = value;
        document.body.appendChild(probe);
        const resolved = getComputedStyle(probe).color;
        probe.remove();
        return resolved;
      };
      const channels = (color) => {
        const match = color.match(/[\d.]+/g) ?? [];
        return match.slice(0, 3).map(Number);
      };
      const luminance = (color) => {
        const [r, g, b] = channels(color).map((channel) => {
          const c = channel / 255;
          return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
      };
      const contrast = (fg, bg) => {
        const a = luminance(fg);
        const b = luminance(bg);
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      };

      // Semi-transparent roles (accent-soft, hover) must be composited over the
      // page canvas before measuring, or the alpha is read as a solid colour.
      const canvasColor = rgb("var(--hc-bg-canvas)");
      const composite = (color, under) => {
        const parts = color.match(/[\d.]+/g)?.map(Number) ?? [];
        const alpha = parts.length > 3 ? parts[3] : 1;
        const target = channels(under);
        const base = channels(color);
        const mixed = [0, 1, 2].map((index) =>
          Math.round(base[index] * alpha + target[index] * (1 - alpha)),
        );
        return `rgb(${mixed[0]}, ${mixed[1]}, ${mixed[2]})`;
      };

      const contrastPairs = pairs.map(([label, fgToken, bgToken]) => {
        const fgRaw = rgb(`var(${fgToken})`);
        const bgRaw = rgb(`var(${bgToken})`);
        const bg = composite(bgRaw, canvasColor);
        const fg = composite(fgRaw, bg);
        return { label, fgToken, bgToken, fg, bg, ratio: Number(contrast(fg, bg).toFixed(2)) };
      });

      const smallest = { size: 99, sample: "" };
      const tiny = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        const text = node.textContent?.trim() ?? "";
        if (text.length === 0) continue;
        const parent = node.parentElement;
        if (!parent) continue;
        const size = parseFloat(getComputedStyle(parent).fontSize);
        if (size < smallest.size) {
          smallest.size = size;
          smallest.sample = text.slice(0, 24);
        }
        if (size < 12) tiny.push(`${size}px:${text.slice(0, 16)}`);
      }

      const boxes = {};
      for (const selector of ["header", "aside", "main", "article", "section"]) {
        const el = document.querySelector(selector);
        if (!el) continue;
        const rect = el.getBoundingClientRect();
        boxes[selector] = {
          w: Math.round(rect.width),
          h: Math.round(rect.height),
          text: (el.textContent ?? "").trim().length,
        };
      }

      const clipped = [];
      for (const el of Array.from(document.querySelectorAll<HTMLElement>("body *"))) {
        const style = getComputedStyle(el);
        if (style.overflow === "visible") continue;
        if (el.scrollWidth > el.clientWidth + 2 && (style.textOverflow !== "ellipsis" || el.clientWidth === 0)) {
          clipped.push(`${el.tagName.toLowerCase()}.${el.className.slice(0, 40)} ${el.clientWidth}<${el.scrollWidth}`);
        }
      }

      const reading = document.querySelector(".db-reading");
      const measure = reading
        ? Math.round(reading.getBoundingClientRect().width)
        : null;

      return {
        measure,
        fonts: {
          serif: document.fonts.check('16px "Noto Serif SC"'),
          sans: document.fonts.check('16px "Noto Sans SC"'),
          mono: document.fonts.check('16px "Cascadia Mono"'),
          body: getComputedStyle(document.body).fontFamily,
        },
        contrastPairs,
        smallest,
        tinyCount: tiny.length,
        tinySample: tiny.slice(0, 8),
        boxes,
        clipped: clipped.slice(0, 6),
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      };
    }, PAIRS);

    await agentContext.close();

    const mobileContext = await browser.newContext({
      viewport: { width: 390, height: 844 },
      colorScheme: theme,
      locale: "zh-CN",
      isMobile: true,
      hasTouch: true,
    });
    const mobilePage = await mobileContext.newPage();
    await mobilePage.goto(`${base}/directions/${dir}/chat`, { waitUntil: "networkidle" });
    await mobilePage.waitForTimeout(250);
    const mobile = await mobilePage.evaluate(() => {
      const small = [];
      for (const el of Array.from(document.querySelectorAll<HTMLElement>("button, a[href]"))) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        if (rect.height < 40 || rect.width < 40) {
          small.push(
            `${el.tagName.toLowerCase()} ${Math.round(rect.width)}×${Math.round(rect.height)} "${(el.textContent ?? "").trim().slice(0, 12)}"`,
          );
        }
      }
      return {
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        smallTargets: small.slice(0, 10),
        smallTargetCount: small.length,
      };
    });
    await mobileContext.close();

    report.push({ dir, theme, errors, desktop, mobile });
    console.log(
      `${dir}/${theme} contrast-min=${Math.min(...desktop.contrastPairs.map((pair) => pair.ratio)).toFixed(2)} ` +
        `minText=${desktop.smallest.size}px tiny=${desktop.tinyCount} clip=${desktop.clipped.length} ` +
        `mobileTargets=${mobile.smallTargetCount} err=${errors.length}`,
    );
  }
}

await browser.close();
await writeFile(join(outDir, "audit.json"), JSON.stringify(report, null, 2));
console.log(`\nwrote ${join(outDir, "audit.json")}`);
