/**
 * 把样式表里「与设计令牌等值」的硬编码字号换成令牌引用。
 *
 * 只做等值替换（12/13/14/15/16/20/24px → --fn-text-*），因此不会改变任何
 * 计算后的视觉结果；不在尺度上的值（11/17px 等）留给需要视觉验收的批次。
 *
 * 用法：
 *   node scripts/codemod-tokens.mjs            # 干跑，只打印统计
 *   node scripts/codemod-tokens.mjs --write    # 落盘
 */

import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const ROOT = resolve(process.cwd(), "src");
const GENERATED = join(ROOT, "styles", "tokens.generated.css");
const WRITE = process.argv.includes("--write");

/**
 * 不参与本批次的目录：首页、插件市场、搜索配置、移动端各自有正在推进的
 * 工作线或明确的改动禁区，等对应批次单独处理。
 */
const SKIP = [
  "pages/Home/",
  "pages/Admin/Plugins/",
  "pages/Settings/SearchConfig/",
  "mobile/",
];

/** --fn-text-2xs: 12px; → { 12: "2xs" } */
function fontSizeTokens() {
  const css = readFileSync(GENERATED, "utf8");
  const map = new Map();
  for (const line of css.split("\n")) {
    const match = /--fn-text-([\w-]+):\s*(\d+)px;\s*$/.exec(line.trim());
    if (!match) continue;
    map.set(Number(match[2]), match[1]);
  }
  return map;
}

function styleFiles(dir = ROOT) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "node_modules" || entry === "dist") continue;
      out.push(...styleFiles(full));
      continue;
    }
    if (!/\.(css|less)$/.test(entry)) continue;
    if (full === GENERATED) continue;
    const rel = relative(ROOT, full).replace(/\\/g, "/");
    if (SKIP.some((prefix) => rel.startsWith(prefix))) continue;
    out.push(full);
  }
  return out;
}

const TOKENS = fontSizeTokens();
const DECLARATION = /(^|[\s;{])font-size:\s*(\d+(?:\.\d+)?)px(\s*!important)?\s*(?=[;}])/g;

const changed = [];
let replacements = 0;

for (const file of styleFiles()) {
  const before = readFileSync(file, "utf8");
  let count = 0;
  const after = before.replace(DECLARATION, (match, prefix, value, important) => {
    const key = TOKENS.get(Number(value));
    if (!key) return match;
    count += 1;
    return `${prefix}font-size: var(--fn-text-${key})${important ?? ""}`;
  });
  if (count === 0) continue;
  replacements += count;
  changed.push({ file: relative(ROOT, file).replace(/\\/g, "/"), count });
  if (WRITE) writeFileSync(file, after);
}

changed.sort((a, b) => b.count - a.count);
for (const row of changed.slice(0, 15)) {
  console.log(`${String(row.count).padStart(4)}  ${row.file}`);
}
if (changed.length > 15) console.log(`  ... 其余 ${changed.length - 15} 个文件`);
console.log(
  `${WRITE ? "已写入" : "干跑"}：${changed.length} 个文件，${replacements} 处字号等值替换`,
);
