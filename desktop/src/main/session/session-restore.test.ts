import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  chatLocation,
  isRestorableUrl,
  readSessionSnapshot,
  restoreUrl,
  routeOnlyUrl,
  sessionIdOf,
  writeSessionSnapshot,
} from "./session-restore";

const ORIGIN = "octop://app";
const FILE = join(mkdtempSync(join(tmpdir(), "octop-session-")), "session.json");

test("a default snapshot exits cleanly and has no url", () => {
  assert.deepEqual(readSessionSnapshot(FILE), { url: null, cleanExit: true, sessionId: null });
});

test("a snapshot round-trips", () => {
  writeSessionSnapshot(FILE, {
    url: "octop://app/chat/thr_1?tab=files",
    cleanExit: false,
    sessionId: "thr_1",
  });
  assert.deepEqual(readSessionSnapshot(FILE), {
    url: "octop://app/chat/thr_1?tab=files",
    cleanExit: false,
    sessionId: "thr_1",
  });
});

test("garbage on disk falls back to a clean default", () => {
  writeFileSync(FILE, "{not json", "utf8");
  assert.deepEqual(readSessionSnapshot(FILE), { url: null, cleanExit: true, sessionId: null });
});

test("only same-origin app routes are restorable", () => {
  assert.equal(isRestorableUrl("octop://app/chat/thr_1", ORIGIN), true);
  assert.equal(isRestorableUrl("octop://app/", ORIGIN), true);
  assert.equal(isRestorableUrl("https://web.example.com/chat", ORIGIN), false);
  assert.equal(isRestorableUrl("octop://other/chat", ORIGIN), false);
  assert.equal(isRestorableUrl("octop://app/login", ORIGIN), false);
  assert.equal(isRestorableUrl("octop://app/setup", ORIGIN), false);
  assert.equal(isRestorableUrl("octop://app/invite", ORIGIN), false);
});

test("a clean exit still reopens the last route", () => {
  assert.equal(
    restoreUrl({ url: "octop://app/chat/thr_1", cleanExit: true, sessionId: "thr_1" }, ORIGIN, "light"),
    "octop://app/chat/thr_1?octopTheme=light",
  );
});

test("an unclean exit reopens the last conversation with the theme", () => {
  const restored = restoreUrl(
    { url: "octop://app/chat/thr_1?tab=files", cleanExit: false, sessionId: "thr_1" },
    ORIGIN,
    "dark",
  );
  assert.equal(restored, "octop://app/chat/thr_1?tab=files&octopTheme=dark");
});

test("the setup wall goes to the normal entry", () => {
  assert.equal(restoreUrl({ url: "octop://app/setup", cleanExit: false, sessionId: null }, ORIGIN, "light"), null);
});

test("chat locations expose the agent and optional session", () => {
  assert.deepEqual(chatLocation("octop://app/chat/agent_a", ORIGIN), {
    agentId: "agent_a",
    sessionId: null,
  });
  assert.deepEqual(chatLocation("octop://app/chat/agent_a/sess_1?x=1", ORIGIN), {
    agentId: "agent_a",
    sessionId: "sess_1",
  });
  assert.equal(chatLocation("octop://app/experts", ORIGIN), null);
  assert.equal(sessionIdOf("octop://app/chat/agent_a", ORIGIN), null);
});

test("a missing session falls back to the route without the session id", () => {
  assert.equal(
    routeOnlyUrl("octop://app/chat/agent_a/sess_1?tab=files", ORIGIN, "dark"),
    "octop://app/chat/agent_a?tab=files&octopTheme=dark",
  );
  assert.equal(routeOnlyUrl("octop://app/chat/agent_a", ORIGIN, "dark"), null);
});
