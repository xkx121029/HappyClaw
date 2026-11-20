/**
 * Accessibility guard.
 *
 * Static checks only — they exist so a new component cannot quietly regress the
 * patterns the refactor established. Runtime coverage (axe, keyboard walks) is a
 * manual checklist item; these catch the mechanical mistakes.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Vitest rewrites `import.meta.url` to a non-file URL, so resolve from the
 * project root instead: these tests always run with cwd = `dashboard/`.
 */
const SRC = resolve(process.cwd(), "src");

function sourceFiles(dir = SRC): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "node_modules") continue;
      out.push(...sourceFiles(full));
      continue;
    }
    if (!/\.tsx$/.test(entry)) continue;
    if (/\.(test|spec)\.tsx$/.test(entry)) continue;
    out.push(full);
  }
  return out;
}

function read(file: string): string {
  return readFileSync(file, "utf8");
}

/** Opening tag starting at `start`, brace- and quote-aware. */
function openTagAt(text: string, start: number): { tag: string; end: number } {
  let i = start;
  let brace = 0;
  let quote = "";
  for (; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      if (ch === "\\") i += 1;
      else if (ch === quote) quote = "";
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") {
      quote = ch;
      continue;
    }
    if (ch === "{") brace += 1;
    else if (ch === "}") brace -= 1;
    else if (ch === ">" && brace === 0) return { tag: text.slice(start, i + 1), end: i };
  }
  return { tag: text.slice(start), end: text.length };
}

function lineOf(text: string, index: number): number {
  return text.slice(0, index).split("\n").length;
}

/**
 * Interactive elements that only respond to Enter. A div acting as a button must
 * accept Space as well — that is the platform convention users rely on.
 */
function enterOnlyHandlers(): string[] {
  const offenders: string[] = [];
  // `\1` back-reference: the handler ignores the event and hardcodes the key.
  const ENTER_ONLY = /onKeyDown=\{\((\w+)\) => \1\.key === "Enter"(?! \|\|)/;
  for (const file of sourceFiles()) {
    if (ENTER_ONLY.test(read(file))) {
      offenders.push(relative(SRC, file).replace(/\\/g, "/"));
    }
  }
  return [...new Set(offenders)];
}

/**
 * Clickable non-interactive elements with no keyboard equivalent.
 *
 * Excluded: backdrops (role=presentation/none), aria-hidden decoration,
 * containers whose role is a landmark/dialog (keyboard handling lives on the
 * focusable children), and pure `stopPropagation` event blockers.
 */
function mouseOnlyControls(): string[] {
  const offenders: string[] = [];
  /** Roles that describe a container, not a control — no key handler needed. */
  const CONTAINER_ROLE =
    /role="(presentation|none|dialog|alertdialog|menu|menubar|listbox|tablist|toolbar|group|separator|region|article|status|alert|log)"/;
  for (const file of sourceFiles()) {
    const text = read(file);
    for (const match of text.matchAll(/<(div|span|li|tr|td|section)\b/g)) {
      const { tag } = openTagAt(text, match.index);
      if (!/\bonClick=/.test(tag)) continue;
      if (/aria-hidden/.test(tag)) continue;
      if (CONTAINER_ROLE.test(tag)) continue;
      if (/onClick=\{[^}]*stopPropagation\(\)[^}]*\}\s*\/?>/.test(tag)) continue;
      // A named helper that only stops the event (e.g. `stopRowEvent`).
      if (/onClick=\{\w*[Ss]top\w*\}\s/.test(tag)) continue;
      const hasRole =
        /role="(button|tab|link|option|menuitem|switch|checkbox)"/.test(tag) ||
        // Conditional role: `role={x ? "button" : undefined}`.
        /role=\{/.test(tag);
      const hasKey = /\bonKeyDown=/.test(tag);
      // A role without a key handler is just as broken as no role at all.
      if (hasRole && hasKey) continue;
      offenders.push(
        `${relative(SRC, file).replace(/\\/g, "/")}:${lineOf(text, match.index)}`,
      );
    }
  }
  return offenders;
}

/**
 * Icon-only antd Buttons must carry an accessible name. Reading the visible
 * label out of JSX is not reliable here, so the rule is: `icon=` and no
 * children means `aria-label` is required.
 */
function unlabelledIconButtons(): string[] {
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    const text = read(file);
    for (const match of text.matchAll(/<Button\b/g)) {
      const { tag, end } = openTagAt(text, match.index);
      if (!/\bicon=/.test(tag)) continue;
      if (/aria-label|aria-labelledby|title=/.test(tag)) continue;
      if (!/\/>\s*$/.test(tag)) {
        const rest = text.slice(end + 1, end + 600);
        const closeIdx = rest.indexOf("</Button>");
        if (closeIdx === -1) continue;
        const visible = rest
          .slice(0, closeIdx)
          .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
          .replace(/<[^>]*>/g, "")
          .replace(/\s+/g, "");
        if (visible.length > 0) continue;
      }
      offenders.push(
        `${relative(SRC, file).replace(/\\/g, "/")}:${lineOf(text, match.index)}`,
      );
    }
  }
  return offenders;
}

describe("accessibility", () => {
  it("no interactive element handles Enter but not Space", () => {
    expect(enterOnlyHandlers()).toEqual([]);
  });

  it("every clickable surface has role + keyboard activation", () => {
    expect(mouseOnlyControls()).toEqual([]);
  });

  it("icon-only antd buttons have an accessible name", () => {
    expect(unlabelledIconButtons()).toEqual([]);
  });

  it("the sidebar avatar trigger is reachable and labelled", () => {
    const text = read(join(SRC, "components/AvatarDropdown.tsx"));
    expect(text).toContain("aria-label={displayName}");
    expect(text).toContain("aria-expanded={menuOpen}");
  });

  it("body text never renders below 12px", () => {
    // The generated scale is the contract; a hard-coded 11px in a module would
    // bypass it, so both are checked.
    const small: string[] = [];
    for (const file of sourceFiles()) {
      const text = read(file);
      for (const match of text.matchAll(/fontSize:\s*(\d+)[,}]/g)) {
        if (Number(match[1]) < 12) {
          small.push(`${relative(SRC, file)}: ${match[1]}px`);
        }
      }
    }
    expect(small).toEqual([]);
  });
});
