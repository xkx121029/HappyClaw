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

const ORIGIN = "happyclaw://app";
const FILE = join(mkdtempSync(join(tmpdir(), "happyclaw-session-")), "session.json");

test("a default snapshot exits cleanly and has no url", () => {
  assert.deepEqual(readSessionSnapshot(FILE), { url: null, cleanExit: true, sessionId: null });
});

test("a snapshot round-trips", () => {
  writeSessionSnapshot(FILE, {
    url: "happyclaw://app/chat/thr_1?tab=files",
    cleanExit: false,
    sessionId: "thr_1",
  });
  assert.deepEqual(readSessionSnapshot(FILE), {
    url: "happyclaw://app/chat/thr_1?tab=files",
    cleanExit: false,
    sessionId: "thr_1",
  });
});

test("garbage on disk falls back to a clean default", () => {
  writeFileSync(FILE, "{not json", "utf8");
  assert.deepEqual(readSessionSnapshot(FILE), { url: null, cleanExit: true, sessionId: null });
});

test("only same-origin app routes are restorable", () => {
  assert.equal(isRestorableUrl("happyclaw://app/chat/thr_1", ORIGIN), true);
  assert.equal(isRestorableUrl("happyclaw://app/", ORIGIN), true);
  assert.equal(isRestorableUrl("https://web.example.com/chat", ORIGIN), false);
  assert.equal(isRestorableUrl("happyclaw://other/chat", ORIGIN), false);
  assert.equal(isRestorableUrl("happyclaw://app/login", ORIGIN), false);
  assert.equal(isRestorableUrl("happyclaw://app/setup", ORIGIN), false);
  assert.equal(isRestorableUrl("happyclaw://app/invite", ORIGIN), false);
});

test("a clean exit still reopens the last route", () => {
  assert.equal(
    restoreUrl({ url: "happyclaw://app/chat/thr_1", cleanExit: true, sessionId: "thr_1" }, ORIGIN, "light"),
    "happyclaw://app/chat/thr_1?happyclawTheme=light",
  );
});

test("an unclean exit reopens the last conversation with the theme", () => {
  const restored = restoreUrl(
    { url: "happyclaw://app/chat/thr_1?tab=files", cleanExit: false, sessionId: "thr_1" },
    ORIGIN,
    "dark",
  );
  assert.equal(restored, "happyclaw://app/chat/thr_1?tab=files&happyclawTheme=dark");
});

test("the setup wall goes to the normal entry", () => {
  assert.equal(restoreUrl({ url: "happyclaw://app/setup", cleanExit: false, sessionId: null }, ORIGIN, "light"), null);
});

test("chat locations expose the agent and optional session", () => {
  assert.deepEqual(chatLocation("happyclaw://app/chat/agent_a", ORIGIN), {
    agentId: "agent_a",
    sessionId: null,
  });
  assert.deepEqual(chatLocation("happyclaw://app/chat/agent_a/sess_1?x=1", ORIGIN), {
    agentId: "agent_a",
    sessionId: "sess_1",
  });
  assert.equal(chatLocation("happyclaw://app/experts", ORIGIN), null);
  assert.equal(sessionIdOf("happyclaw://app/chat/agent_a", ORIGIN), null);
});

test("a missing session falls back to the route without the session id", () => {
  assert.equal(
    routeOnlyUrl("happyclaw://app/chat/agent_a/sess_1?tab=files", ORIGIN, "dark"),
    "happyclaw://app/chat/agent_a?tab=files&happyclawTheme=dark",
  );
  assert.equal(routeOnlyUrl("happyclaw://app/chat/agent_a", ORIGIN, "dark"), null);
});
