import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  isRestorableUrl,
  readSessionSnapshot,
  recoveryUrl,
  writeSessionSnapshot,
} from "./session-restore";

const ORIGIN = "octop://app";
const FILE = join(mkdtempSync(join(tmpdir(), "octop-session-")), "session.json");

test("a default snapshot exits cleanly and has no url", () => {
  assert.deepEqual(readSessionSnapshot(FILE), { url: null, cleanExit: true });
});

test("a snapshot round-trips", () => {
  writeSessionSnapshot(FILE, { url: "octop://app/chat/thr_1?tab=files", cleanExit: false });
  assert.deepEqual(readSessionSnapshot(FILE), {
    url: "octop://app/chat/thr_1?tab=files",
    cleanExit: false,
  });
});

test("garbage on disk falls back to a clean default", () => {
  writeFileSync(FILE, "{not json", "utf8");
  assert.deepEqual(readSessionSnapshot(FILE), { url: null, cleanExit: true });
});

test("only same-origin app routes are restorable", () => {
  assert.equal(isRestorableUrl("octop://app/chat/thr_1", ORIGIN), true);
  assert.equal(isRestorableUrl("octop://app/", ORIGIN), true);
  assert.equal(isRestorableUrl("https://octop.cloud/chat", ORIGIN), false);
  assert.equal(isRestorableUrl("octop://other/chat", ORIGIN), false);
  assert.equal(isRestorableUrl("octop://app/login", ORIGIN), false);
  assert.equal(isRestorableUrl("octop://app/setup", ORIGIN), false);
});

test("a clean exit never restores", () => {
  assert.equal(
    recoveryUrl({ url: "octop://app/chat/thr_1", cleanExit: true }, ORIGIN, "light"),
    null,
  );
});

test("an unclean exit reopens the last conversation with the theme", () => {
  const restored = recoveryUrl(
    { url: "octop://app/chat/thr_1?tab=files", cleanExit: false },
    ORIGIN,
    "dark",
  );
  assert.equal(restored, "octop://app/chat/thr_1?tab=files&octopTheme=dark");
});

test("an unclean exit on the setup wall goes to the normal entry", () => {
  assert.equal(
    recoveryUrl({ url: "octop://app/setup", cleanExit: false }, ORIGIN, "light"),
    null,
  );
});
