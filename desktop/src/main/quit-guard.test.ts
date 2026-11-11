import assert from "node:assert/strict";
import { test } from "node:test";

import { inspectBeforeQuit, quitPrompt } from "./quit-guard";

function jsonResponse(body: unknown, ok = true): Response {
  return new Response(JSON.stringify(body), {
    status: ok ? 200 : 500,
    headers: { "content-type": "application/json" },
  });
}

test("updates and signals never query the sidecar", async () => {
  let calls = 0;
  const fetchImpl = (async () => {
    calls += 1;
    return jsonResponse({ busy: true, counts: { agent_turn: 1 } });
  }) as unknown as typeof fetch;

  const update = await inspectBeforeQuit({ reason: "update", backendPort: 3210, fetchImpl });
  const signal = await inspectBeforeQuit({ reason: "signal", backendPort: 3210, fetchImpl });
  assert.equal(update.ask, false);
  assert.equal(signal.ask, false);
  assert.equal(calls, 0);
});

test("no sidecar means no query", async () => {
  let calls = 0;
  const fetchImpl = (async () => {
    calls += 1;
    return jsonResponse({ busy: true });
  }) as unknown as typeof fetch;

  const decision = await inspectBeforeQuit({ reason: "user", backendPort: 0, fetchImpl });
  assert.equal(decision.ask, false);
  assert.equal(calls, 0);
});

test("a busy sidecar asks, with per-kind counts", async () => {
  const decision = await inspectBeforeQuit({
    reason: "user",
    backendPort: 3210,
    fetchImpl: (async () =>
      jsonResponse({
        busy: true,
        counts: { agent_turn: 1, terminal: 2 },
      })) as unknown as typeof fetch,
  });
  assert.equal(decision.ask, true);
  assert.equal(decision.total, 3);
  assert.deepEqual(decision.counts, { agent_turn: 1, terminal: 2 });
});

test("an idle sidecar exits silently", async () => {
  const decision = await inspectBeforeQuit({
    reason: "user",
    backendPort: 3210,
    fetchImpl: (async () =>
      jsonResponse({ busy: false, counts: {} })) as unknown as typeof fetch,
  });
  assert.equal(decision.ask, false);
});

test("a failed or slow query never blocks quitting", async () => {
  const failed = await inspectBeforeQuit({
    reason: "user",
    backendPort: 3210,
    fetchImpl: (async () => jsonResponse({}, false)) as unknown as typeof fetch,
  });
  assert.equal(failed.ask, false);

  const hanging = (async (_url: string, init?: { signal?: AbortSignal }) =>
    new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new Error("aborted")));
    })) as unknown as typeof fetch;
  const timedOut = await inspectBeforeQuit({
    reason: "user",
    backendPort: 3210,
    fetchImpl: hanging,
    timeoutMs: 10,
  });
  assert.equal(timedOut.ask, false);
});

test("unsaved work asks even when the sidecar is idle or absent", async () => {
  const idle = await inspectBeforeQuit({
    reason: "user",
    backendPort: 3210,
    unsaved: true,
    fetchImpl: (async () => jsonResponse({ busy: false })) as unknown as typeof fetch,
  });
  assert.equal(idle.ask, true);

  const absent = await inspectBeforeQuit({ reason: "user", backendPort: 0, unsaved: true });
  assert.equal(absent.ask, true);
});

test("prompt copy names the work being interrupted", () => {
  const zh = quitPrompt(
    { ask: true, counts: { agent_turn: 1, terminal: 2 }, total: 3, unsaved: true },
    "zh-CN",
  );
  assert.equal(zh?.message, "还有 3 个任务正在运行");
  assert.match(zh?.detail ?? "", /对话 1 个 · 终端会话 2 个/);
  assert.match(zh?.detail ?? "", /未保存/);

  const en = quitPrompt(
    { ask: true, counts: { agent_turn: 1 }, total: 1, unsaved: false },
    "en-US",
  );
  assert.equal(en?.message, "1 task still running");
  assert.equal(quitPrompt({ ask: false, counts: {}, total: 0, unsaved: false }, "zh-CN"), null);
});
