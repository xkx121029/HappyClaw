import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { readWindowState, usableWindowBounds, writeWindowState } from "./window-state";

const MIN = { width: 960, height: 600 };
const AREAS = [{ x: 0, y: 0, width: 1920, height: 1080 }];
const FILE = join(mkdtempSync(join(tmpdir(), "octop-window-state-")), "window.json");

test("a saved rect round-trips and survives a missing file", () => {
  assert.equal(readWindowState(FILE), null);
  writeWindowState(FILE, { x: 120, y: 80, width: 1280, height: 800, maximized: true });
  assert.deepEqual(readWindowState(FILE), {
    x: 120,
    y: 80,
    width: 1280,
    height: 800,
    maximized: true,
  });
});

test("malformed values are dropped instead of applied", () => {
  writeFileSync(FILE, JSON.stringify({ x: "left", y: 40, width: 0, height: 0 }), "utf8");
  assert.deepEqual(readWindowState(FILE), { y: 40, maximized: false });
});

test("a new window has no explicit position", () => {
  assert.equal(usableWindowBounds({}, AREAS, MIN), null);
});

test("the stored size is clamped to the dashboard floor", () => {
  assert.deepEqual(usableWindowBounds({ x: 10, y: 10, width: 400, height: 300 }, AREAS, MIN), {
    x: 10,
    y: 10,
    width: 960,
    height: 600,
  });
});

test("a window on a disconnected display is not restored there", () => {
  assert.equal(
    usableWindowBounds({ x: 4000, y: 300, width: 1280, height: 800 }, AREAS, MIN),
    null,
  );
});
