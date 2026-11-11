import assert from "node:assert/strict";
import { test } from "node:test";

import { createManualBackup } from "./manual-backup";

test("a manual backup posts the device token and returns the archive", async () => {
  const seen: Array<{ url: string; init?: RequestInit }> = [];
  const fetchImpl = (async (url: string, init?: RequestInit) => {
    seen.push({ url, init });
    return new Response(JSON.stringify({ name: "octop-backup-1.tar.gz", size: 1024 }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;

  const result = await createManualBackup({
    baseUrl: "http://127.0.0.1:3210",
    token: "jwt-value",
    fetchImpl,
  });
  assert.deepEqual(result, { ok: true, name: "octop-backup-1.tar.gz", size: 1024, message: null });
  const request = seen[0];
  assert.ok(request);
  assert.equal(request.url, "http://127.0.0.1:3210/api/backup/create");
  assert.equal(
    (request.init?.headers as Record<string, string>).authorization,
    "Bearer jwt-value",
  );
  assert.match(String(request.init?.body), /"include_chats":true/);
});

test("the backend's error message reaches the dialog", async () => {
  const fetchImpl = (async () =>
    new Response(JSON.stringify({ detail: "备份正在进行中" }), {
      status: 409,
      headers: { "content-type": "application/json" },
    })) as unknown as typeof fetch;

  const result = await createManualBackup({
    baseUrl: "http://127.0.0.1:3210",
    token: "jwt-value",
    fetchImpl,
  });
  assert.equal(result.ok, false);
  assert.equal(result.message, "备份正在进行中");
});

test("a transport failure is reported, not thrown", async () => {
  const fetchImpl = (async () => {
    throw new Error("connect ECONNREFUSED");
  }) as unknown as typeof fetch;
  const result = await createManualBackup({
    baseUrl: "http://127.0.0.1:3210",
    token: "jwt-value",
    fetchImpl,
  });
  assert.equal(result.ok, false);
  assert.match(result.message ?? "", /ECONNREFUSED/);
});
